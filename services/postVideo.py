
import time
import os
import sys
import redis

from flask import render_template, request, current_app, jsonify, redirect, session

from init import app, rdb
from utils.interceptors import loginOptional, jsonRequest, loginRequiredJSON
from utils.jsontools import *
from utils.http import post_raw
from utils.rwlock import usingResource, modifyingResource
from utils.exceptions import UserError
from bson.json_util import dumps, loads
from bson import ObjectId

from db import tagdb
from spiders import dispatch
from config import VideoConfig, TagsConfig
from utils.logger import log, getEventID
from services.tcb import filterOperation

if os.getenv("FLASK_ENV", "development") == "production" :
	SCRAPER_ADDRESS = 'http://scraper:5003'
else :
	SCRAPER_ADDRESS = 'http://localhost:5003'

@usingResource('tags')
def _verifyTags(tags) :
	tagdb.verify_tags(tags)

def postTask(json_str) :
	ret_obj = loads(post_raw(SCRAPER_ADDRESS, json_str.encode('utf-8')).text)
	return ret_obj['task_id']

def _createJsonForPosting(url, tags, dst_copy, dst_playlist, dst_rank, other_copies, user, playlist_ordered = None) :
	return dumps({
		'url' : url,
		'tags' : tags,
		'dst_copy' : dst_copy,
		'dst_playlist' : dst_playlist,
		'dst_rank' : dst_rank,
		'other_copies' : other_copies,
		'user' : user,
		'playlist_ordered' : playlist_ordered,
		'event_id': getEventID()
	})

def getTaskParamas(task_id) :
	key = f'task-{task_id}'
	json_str = rdb.get(key)
	if json_str :
		json_obj = loads(json_str)
		return json_obj['params']
	else :
		return None

def listCurrentTasks(user, page = 0, page_size = 100) :
	key = 'posttasks-' + str(user['_id'])
	return rdb.lrange(key, page * page_size, (page + 1) * page_size)

def listCurrentTasksWithParams(user, page = 0, page_size = 100) :
	task_ids = listCurrentTasks(user, page, page_size)
	ret_map = {}
	for tid in task_ids :
		tid = tid.decode('ascii')
		param = getTaskParamas(tid)
		if param :
			ret_map[tid] = param
	return ret_map

def listFailedPosts(user, page = 0, page_size = 100000) :
	uid = ObjectId(user['_id'])
	result = tagdb.db.failed_posts.find({'uid': uid})
	result = result.skip(page * page_size).limit(page_size)
	return result

def postVideo(user, url, tags, copy, pid, rank):
	log(obj = {'url': url, 'tags': tags, 'copy': copy, 'pid': pid, 'rank': rank})
	filterOperation('postVideo', user)
	tags = [tag.strip() for tag in tags]
	if not url :
		raise UserError('EMPTY_URL')
	if len(url) > VideoConfig.MAX_URL_LENGTH :
		raise UserError('URL_TOO_LONG')
	if len(tags) > VideoConfig.MAX_TAGS_PER_VIDEO :
		raise UserError('TAGS_LIMIT_EXCEEDED')
	obj, cleanURL = dispatch(url)
	if obj is None:
		raise UserError('UNSUPPORTED_WEBSITE')
	if not cleanURL :
		raise UserError('EMPTY_URL')
	_verifyTags(tags)
	log(obj = {'url': cleanURL})
	task_id = postTask(_createJsonForPosting(cleanURL, tags, copy, pid, rank, [], user))
	return task_id

def postVideoBatch(user, videos, tags, copy, pid, rank, as_copies):
	log(obj = {'urls': videos, 'tags': tags, 'copy': copy, 'pid': pid, 'rank': rank, 'as_copies': as_copies})
	filterOperation('postVideoBatch', user)
	tags = [tag.strip() for tag in tags]
	if not videos :
		raise UserError('EMPTY_LIST')
	if len(videos) > VideoConfig.MAX_BATCH_POST_COUNT :
		raise UserError('POST_LIMIT_EXCEEDED')
	if len(tags) > VideoConfig.MAX_TAGS_PER_VIDEO :
		raise UserError('TAGS_LIMIT_EXCEEDED')
	_verifyTags(tags)
	cleanURL_objs = []
	unique_ids = []
	for url in videos :
		url = url.strip()
		if not url:
			continue
		obj, cleanURL = dispatch(url)
		# Here we allow batch post to be partially successful
		if obj is not None :
			uid = obj.unique_id(obj, cleanURL)
			if not uid in unique_ids : # remove duplicated items
				cleanURL_objs.append((obj, cleanURL))
				unique_ids.append(uid)
		else :
			log('dispatcher', level = 'WARN', obj = {'failed_url': url})
	task_ids = []
	for idx, (obj, cleanURL) in enumerate(cleanURL_objs) :
		log(obj = {'url': cleanURL})
		next_idx = idx if rank >= 0 else 0
		task_id = postTask(_createJsonForPosting(cleanURL, tags, copy, pid, rank + next_idx, unique_ids if as_copies else [], user, unique_ids))
		task_ids.append(task_id)
	return task_ids

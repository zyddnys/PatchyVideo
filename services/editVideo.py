
from db import tagdb, client
from utils.dbtools import makeUserMeta, MongoTransaction
from utils.rwlock import usingResource, modifyingResource
from utils.exceptions import UserError
from utils.tagtools import translateTagsToPreferredLanguage
from services.postVideo import postTask
from services.tcb import filterSingleVideo, filterOperation

from init import rdb
from bson import ObjectId
import redis_lock
from config import VideoConfig, TagsConfig
from bson.json_util import dumps, loads
from utils.logger import log, getEventID

@usingResource('tags')
def editVideoTags(vid, tags, user):
	log(obj = {'tags': tags, 'vid': vid})
	filterOperation('editVideoTags', user, vid)
	filterSingleVideo(vid, user)
	if len(tags) > VideoConfig.MAX_TAGS_PER_VIDEO :
		raise UserError('TAGS_LIMIT_EXCEEDED')
	tagdb.verify_tags(tags)
	item = tagdb.db.items.find_one({'_id': ObjectId(vid)})
	if item is None:
		raise UserError('ITEM_NOT_EXIST')
	if len(tags) > VideoConfig.MAX_TAGS_PER_VIDEO:
		raise UserError('TOO_MANY_TAGS')
	with redis_lock.Lock(rdb, "videoEdit:" + item['item']['unique_id']), MongoTransaction(client) as s :
		tagdb.update_item_tags(item, tags, makeUserMeta(user), s())
		s.mark_succeed()

def getVideoTags(vid, user_language, user) :
	filterSingleVideo(vid, user)
	item, tags, category_tag_map, tag_category_map = tagdb.retrive_item_with_tag_category_map(vid, user_language)
	return tags

def refreshVideoDetail(vid, user) :
	log(obj = {'vid': vid})
	filterOperation('refreshVideoDetail', user, vid)
	filterSingleVideo(vid, user)
	item = tagdb.retrive_item(vid)
	if item is None :
		raise UserError('ITEM_NOT_EXIST')
	json_str = dumps({
		'url' : item['item']['url'],
		'tags' : [],
		'dst_copy' : '',
		'dst_playlist' : '',
		'dst_rank' : -1,
		'other_copies' : [],
		'user' : user,
		'playlist_ordered' : None,
		'update_video_detail': True,
		'event_id': getEventID()
	})
	postTask(json_str)

def refreshVideoDetailURL(url, user) :
	log(obj = {'url': url})
	filterOperation('refreshVideoDetailURL', user, vid)
	json_str = dumps({
		'url' : url,
		'tags' : [],
		'dst_copy' : '',
		'dst_playlist' : '',
		'dst_rank' : -1,
		'other_copies' : [],
		'user' : user,
		'playlist_ordered' : None,
		'update_video_detail': True,
		'event_id': getEventID()
	})
	postTask(json_str)


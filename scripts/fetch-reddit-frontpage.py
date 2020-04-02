#!/usr/bin/env python3
import inspect, os, sys, copy, pytz, re, glob, csv, uuid, time, requests, math, jsonlines, datetime, shutil

import simplejson as json
import pandas as pd
from dateutil import parser
import datetime
import numpy as np
from collections import Counter, defaultdict
utc=pytz.UTC
import logutil

## LOAD ALGOTRACKER CONFIG
with open("config/algotracker-config.json") as f:
    algotracker_config = json.loads(f.read())


## LOAD CIVILSERVANT CONFIG AND LIBRARIES

ENV = os.environ['CS_ENV']
BASE_DIR = os.environ['ALGOTRACKER_BASE_DIR']
OUTPUT_BASE_DIR = os.environ['ALGOTRACKER_OUTPUT_DIR']
sys.path.append(BASE_DIR)

AIRBRAKE_ENABLED = bool(os.environ["ALGOTRACKER_AIRBRAKE_ENABLED"])
LOG_LEVEL = int(os.environ["ALGOTRACKER_LOG_LEVEL"])
log = logutil.get_logger(ENV, AIRBRAKE_ENABLED, LOG_LEVEL, handle_unhandled_exceptions=True)

PS_RETRIES = 5
PS_RETRY_DELAY = 5

with open(os.path.join(BASE_DIR, "config") + "/{env}.json".format(env=ENV), "r") as config:
    DBCONFIG = json.loads(config.read())

### LOAD SQLALCHEMY
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text, and_, or_, desc
import sqlalchemy.orm.session
import utils.common


db_engine = create_engine("mysql://{user}:{password}@{host}/{database}".format(
    host = DBCONFIG['host'],
    user = DBCONFIG['user'],
    password = DBCONFIG['password'],
    database = DBCONFIG['database']))
DBSession = sessionmaker(bind=db_engine)
db_session = DBSession()

from app.models import *
from app.models import Base, SubredditPage, FrontPage, Subreddit, Post, ModAction
from utils.common import PageType

##################
## CONFIGURATION
opening_date = datetime.datetime.utcnow() -  datetime.timedelta(days=algotracker_config['start_interval_days'])
covid_tokens = algotracker_config['terms']
rank_keys = {
    PageType.HOT: "hot",
    PageType.TOP: "top"
}


##################
## UTILITY METHODS

def post_rankings():
    return {rank_keys[PageType.HOT]:[],
            rank_keys[PageType.TOP]:[]
           }

def post_rankings():
    return {rank_keys[PageType.HOT]:[],
            rank_keys[PageType.TOP]:[]
           }


## Extract a subset of keys
## extract(keys, dict)
extract = lambda x, y: dict(zip(x, map(y.get, x)))

##  Parse Pages
## record the mean and median ups, downs, score
## knowing that they're obfuscated by reddit            

def parsed_page(page):
    page_posts = json.loads(page.page_data)
    
    downs   = [x['downs'] for x in page_posts]
    ups     = [x['ups'] for x in page_posts]
    scores   = [x['score'] for x in page_posts]
    
    return {"created_at":page.created_at,
            "page_type":page.page_type,
            "id": page.id,
            "median_ups"    : np.median(ups),
            "mean_ups"      : np.mean(ups),
            "median_downs"  : np.median(downs),
            "mean_downs"    : np.mean(downs),
            "median_scores" : np.median(scores),
            "mean_scores"   : np.mean(scores),
            "posts"         : page_posts}

## Query and construct rank vectors from CivilServant
def post_rankings():
    return {rank_keys[PageType.HOT]:[],
            rank_keys[PageType.TOP]:[]
           }

## Query and construct rank vectors from CivilServant
def construct_rank_vectors(is_subpage):
    rank_vectors = {}   # rank_vectors[subid][pt][pid][page.created_at] = i
    max_rank_vectors = {} # [pid][subid][pt] = i
    all_pages = {rank_keys[PageType.TOP]:[],
                 rank_keys[PageType.HOT]:[]}

    rank_posts = defaultdict(post_rankings)
    all_posts = defaultdict(post_rankings)
    
    for pt in [PageType.TOP, PageType.HOT]:
        log.info(pt)
        pages = db_session.query(FrontPage).filter(and_(FrontPage.page_type == pt.value,
                                                            FrontPage.created_at >= opening_date))
        for page in pages:
            subid = "FRONT PAGE" ## Vestige from a more general library
            all_pages[rank_keys[pt]].append(parsed_page(page))     
            posts = json.loads(page.page_data)
            
            rank_posts[page.id][rank_keys[pt]] = posts
            
            for i,post in enumerate(posts):
                rank_position = i * -1 # top is 0, descending from there
                pid = post['id']
                post['rank_position'] = rank_position 
                post['front_page']    = rank_keys[pt]
                post['rank_time']     = page.created_at
                post['rank_id']       = page.id
                all_posts[post['id']][rank_keys[pt]].append(post)
                
                #MAX RANK WORK
                if pid not in max_rank_vectors:
                    max_rank_vectors[pid] = {}
                if subid not in max_rank_vectors[pid]:
                    max_rank_vectors[pid][subid] = {}
                if (pt not in max_rank_vectors[pid][subid]) or (rank_position > max_rank_vectors[pid][subid][pt]):
                    # max rank = smallest number placement
                    max_rank_vectors[pid][subid][pt] = rank_position

    for post_id, post in all_posts.items():
        for pt in [PageType.TOP, PageType.HOT]:
            post[rank_keys[pt]] = sorted(post[rank_keys[pt]], 
                                         key = lambda x: x['rank_time'],
                                         reverse=False)
                        
    return max_rank_vectors, all_posts, all_pages, rank_posts

## Query PushShift
def getPSPosts(ids):
    url = "https://api.pushshift.io/reddit/search/submission/?ids={0}".format(
    ",".join(ids)
    )
    data = None
    for attempt in range(1, PS_RETRIES+1):
        try:
            r = requests.get(url)
            r.raise_for_status()
            data = json.loads(r.text)
        except:
            log.exception("Unable to get posts from Pushshift on attempt %d of %d.",
                attempt,
                PS_RETRIES+1)
            time.sleep(PS_RETRY_DELAY)
    return data['data'] if data else []

## Query Most Recent Front Page
def query_most_recent_front_page():
    page_object = db_session.query(FrontPage).order_by(desc('created_at')).first()
    posts = json.loads(page_object.page_data)
    post_data = getPSPosts([x['id'] for x in posts])
    post_data_dict = {}
    for post in post_data:
        post_data_dict[post['id']] = post
    
    for post in posts:
        post.update(post_data_dict[post['id']])
    
    return posts

##################################
## Query data and produce outcome

#srank_vectors, smax_rank_vectors = construct_rank_vectors(True)

rank_vector_start = datetime.datetime.utcnow()

fmax_rank_vectors, db_posts, all_pages, rank_posts = construct_rank_vectors(False)

rank_vector_end = datetime.datetime.utcnow()

log.info("Completed rank vector collection from {0} posts in in {1} seconds".format(
    len(fmax_rank_vectors),
    (rank_vector_end - rank_vector_start).total_seconds()
))


# ### For all posts, Produce the Rank Position for the Whole Observed Period Up to the Last Observation or 6 Hours, Whichever is Longer

log.info("Creating Regular Snapshots for Every Post")
counter = 0
for post in db_posts.values():
    counter += 1
    if counter % 100 == 0:
        sys.stdout.write(".")
        sys.stdout.flush()

    if 'hot' in post.keys() and len(post['hot'])>0:
        prototype_post = extract(['author', 'created_utc', 'subreddit_id', 'id'], 
                                 copy.copy(post['hot'][0]))

    else:
        prototype_post = extract(['author', 'created_utc', 'subreddit_id', 'id'],
                                 copy.copy(post['top'][0]))

    post_id = prototype_post['id']
    post_created = datetime.datetime.utcfromtimestamp(prototype_post['created_utc'])

    created_plus = post_created + datetime.timedelta(hours=6)
    final_observed_time = {}
    timeseries_last_time = {}

    for key in rank_keys.values():
        if key in post.keys() and len(post[key]) > 0:
            final_observed_time[key] = post[key][-1]['rank_time']
        else:
            final_observed_time[key] = created_plus

        if(final_observed_time[key]>created_plus):
            timeseries_last_time[key] = final_observed_time[key]
        else:
            timeseries_last_time[key] = created_plus

    overall_last_time = max([timeseries_last_time[x] for x in rank_keys.values()])

    num_snapshots = 0

    for pt in [PageType.HOT, PageType.TOP]:    
        for page in [p for p in all_pages[rank_keys[pt]] 
                      if p['page_type']==pt.value]:

            page_rank_time = page['created_at']

            ## if the time is ineligible, skip the iteration
            ## or stop iterating entirely
            if(page_rank_time < post_created):
                continue
            if(page_rank_time > overall_last_time):
                break

            page_ranks = rank_posts[page['id']][rank_keys[pt]]
            
            num_snapshots += 1

            ## record the mean and median ups, downs, score
            ## knowing that they're obfuscated by reddit            
            snapshot_obs = {}
            for k in ['median_ups', 'mean_ups','median_downs',
                      'mean_downs', 'median_scores', 'mean_scores']:
                snapshot_obs[k] = page[k]

            ## if this ranking snapshot is already recorded
            ## in the rank times for this post
            ## then add the snapshot observations
            ## and stop iterating
            rank_updated = False
            for page_rank in post[rank_keys[pt]]:
                if(page_rank['rank_id'] == page['id']):
                    page_rank.update(snapshot_obs)
                    rank_updated = True
                    break
            if(rank_updated):
                continue

            ## if this ranking snapshot is not observed
            ## then add it to the list
            snapshot_obs.update(prototype_post)

            snapshot_obs['rank_id']    = page['id']
            snapshot_obs['rank_time']  = page['created_at']
            snapshot_obs['front_page'] = rank_keys[pt]

            for key in ['rank_position', 'score', 
                        'ups', 'downs','num_comments']:
                snapshot_obs[key] = None

            post[rank_keys[pt]].append(snapshot_obs)

## Sort ranks within db_posts now that we have new entries
for post_id, post in db_posts.items():
    for pt in [PageType.TOP, PageType.HOT]:
        post[rank_keys[pt]] = sorted(post[rank_keys[pt]], 
                                     key = lambda x: x['rank_time'],
                                     reverse=False)

#### For every post, assign a column based on whether it was on hot or top at the very end of the observation period
last_page = {}
for key in rank_keys.values():
    last_page[key] = all_pages[key][-1]
    for post_id, post in db_posts.items():
        in_last_page = int(post_id in [x['id'] for x in last_page[key]['posts']])
        for snapshot in post[key]:
            snapshot["in_latest_snapshot".format(key)] = in_last_page

####################################
## Query Post information from Pushshift
fp_post_ids = list(db_posts.keys())

all_posts = {}
page_size = 1000
courtesy_delay = 0.25
est_query_time = 0.3

bg_begin = datetime.datetime.utcnow()

## dict of posts, with a key associated with the post ID
log.info("Loading {0} posts from Pushshift with {1} queries. Estimate time: {2} minutes".format(
    len(fp_post_ids),
    math.ceil(len(fp_post_ids)/page_size),
    math.ceil(math.ceil((len(fp_post_ids)/page_size)*courtesy_delay + (len(fp_post_ids)/page_size)*est_query_time)/60)

))

head = 0
tail = page_size
while(head <= len(fp_post_ids)):
    sys.stdout.write(".")
    sys.stdout.flush()
    ids = fp_post_ids[head:tail]
    if(len(ids)>0):
        posts = getPSPosts(ids)
        for post in posts:
#                post['post_week'] = datetime.datetime.fromtimestamp(post['created_utc']).strftime("%Y%U")
            all_posts[post['id']] = post
    time.sleep(courtesy_delay)
    head += page_size
    tail += page_size

bg_end = datetime.datetime.utcnow()

log.info("Queried Pushshift in {0} seconds".format((bg_end - bg_begin).total_seconds()))

#######################################
## MERGE BAUMGARTNER DATA WITH RANKING DATA
## AND ALSO IDENTIFY COVID-19 RELATED POSTS

## iterate through posts and tag ones related to covid-19
num_matches = 0
total_reviewed = 0

for post_id, post in all_posts.items():
    ltitle = post['title'].lower()
    lselftext = post['selftext'].lower()
    post['covid_19'] = 0 # using 0 and 1 to save space
    for token in covid_tokens:
        if ltitle.find(token) > -1:
            post['covid_19'] = 1 
        if lselftext.find(token) > -1:
            post['covid_19'] = 1
    if(post['covid_19']):
        num_matches += 1

    ## add some additional friction to finding authors by
    ## removing author information from the dataset
    for k in ['author', 'author_cakeday', 'author_flair_background', 'author_flair_css',
              'author_flair_template_id', 'author_flair_text', 'author_flair_type', 'author_fullname',
              'author_patreon_flair', 'author_premium']:
        if k in post.keys():
            del post[k]


snapshots_updated = 0
    ## set max rank and rank duration
for post_id, post in all_posts.items():
    post['max_hot'] = post['max_top'] = 0
    post['front_top_seconds'] = post['front_hot_seconds'] = np.nan
        
        ## max rank column
    if post['id'] in fmax_rank_vectors.keys():
        max_rank = fmax_rank_vectors[post['id']]
        for key,value in max_rank['FRONT PAGE'].items():
            post['week'] = datetime.datetime.fromtimestamp(post['created_utc']).strftime("%Y%U")
            post["max_{0}".format(rank_keys[key])] = value
        
        ## time on front page (top and hot)  
        for key, ranks in db_posts[post['id']].items():
            observed_ranks = [x for x in ranks if x['rank_position']]
            if(len(observed_ranks)>0):
                earliest_rank = observed_ranks[0]['rank_time']
                last_rank = observed_ranks[-1]['rank_time']
                post['front_{0}_seconds'.format(key)] = (last_rank - earliest_rank).total_seconds()
            else:
                post['front_{0}_seconds'.format(key)] = 0

    ## record whether it was in the latest snapshot
    for key in rank_keys.values():
        post["in_latest_snapshot_{0}".format(key)] = 0
        if post['id'] in [x['id'] for x in last_page[key]['posts']]:
           post["in_latest_snapshot_{0}".format(key)] = 1


    ## update db_posts as well
    ## we are updating each snapshot
    ## to make it easy to output to CSV
    for key in [PageType.HOT, PageType.TOP]:
#        post_values = extract([
#          'covid_19'
    #        #'is_self',
    #        #'domain', 'url', 'title', 'body', 'permalink',
    #        #'over_18',
    #        #'author_flair_text', 
    #        #'allow_live_comments',
    #        #'is_video', 'media_only'
#        ], post)

        if rank_keys[key] in db_posts[post_id].keys():
            for snapshot in db_posts[post_id][rank_keys[key]]:
                #snapshot.update(post_values)
                snapshot['covid_19'] = post['covid_19']
                if 'front_page' in snapshot.keys():
                    del snapshot['front_page'] 
                if 'author' in snapshot.keys():
                    del snapshot['author']
                
                snapshots_updated += 1
    
    total_reviewed += 1

log.info("""
Out of {} posts appearing on reddit front pages (TOP and HOT) 
between {} and {}, {} are covid-19 related ({:.02f}%)""".format(
    total_reviewed,
    str(opening_date),
    str(datetime.datetime.utcnow()).split(" ")[0],
    num_matches,
    num_matches/len(all_posts)*100
))

## Create Snapshot Dataframe Lists for Output of Longitudinal Dataset
output_snapshots = {"hot":[],"top":[]}
for post_id, post in db_posts.items():
    for key, snapshots in post.items():
        output_snapshots[key] += snapshots

last_snapshot = max([
    max([x['created_at'] for x in all_pages['hot']]),
    max([x['created_at'] for x in all_pages['top']])
])

timestamp_string = last_snapshot.strftime("%Y%m%d%H%M%S")

######################################
## Create folder and output to files

output_folder = os.path.join(OUTPUT_BASE_DIR, "reddit", timestamp_string)

try:
    os.mkdir(output_folder)
except OSError:
    log.error("Creation of the directory %s failed" % output_folder)
else:
    log.info("Successfully created the directory %s " % output_folder)

## output rank snapshot dataset
for key in list(rank_keys.values()):
    outfile_name = "{0}_rank_timeseries_{1}.csv".format(
        timestamp_string,
        key
    )
    log.info("writing {0}".format(outfile_name))
    pd.DataFrame(output_snapshots[key]).to_csv(os.path.join(output_folder, outfile_name), index=False)

## output dataset of all posts with max rank
all_posts_filename = "{0}_promoted_posts.csv".format(timestamp_string)
log.info("writing {0}".format(all_posts_filename))
pd.DataFrame(list(all_posts.values())).to_csv(os.path.join(output_folder,all_posts_filename), index=False)

## copy configuration file
shutil.copyfile(os.path.join(OUTPUT_BASE_DIR,"../config", "algotracker-config.json"), 
                os.path.join(output_folder, "{0}_algotracker-config.json".format(timestamp_string)))

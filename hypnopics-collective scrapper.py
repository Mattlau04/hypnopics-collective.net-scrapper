#Hypnopics-collective scrapper by Mattlau04
#Started: 05/06/2021
#Last updated: 05/06/2021

import requests
from bs4 import BeautifulSoup
from mechanize import Browser
import re
import os
import json
from urllib.parse import urlparse
import itertools, collections
import time
#from dateutil import parser

base_url = "https://hypnopics-collective.net/smf_forum/index.php?action=gallery;sa=myimages;u={uid};start={offset}"
base_image_url = "https://hypnopics-collective.net/smf_forum/index.php?action=gallery;sa=view;id={pid}"

br = Browser()
reg = re.compile(r"hypnopics-collective.net\/smf_forum\/index.php\?action=gallery;sa=view;id=([0-9]*)")


def get_cookies(username, password): #god they made this wayyyy too hard
    #note to myself if i ever want to improve the login part, the hashing mechanism is this:
    #doForm.hash_passwrd.value = hex_sha1(hex_sha1(doForm.user.value.php_to8bit().php_strtolower() + doForm.passwrd.value.php_to8bit()) + cur_session_id);
    br.open("https://hypnopics-collective.net/smf_forum/index.php?action=login")
    br.select_form(name="frmLogin")
    br["user"] = username
    br["passwrd"] = password
    br.submit()
    return br._ua_handlers['_cookies'].cookiejar #we get da cookies

def get_last_page(cookies, uid):
    r = requests.get(base_url.format(uid=uid, offset=0), cookies=cookies, timeout=300)
    soup = BeautifulSoup(r.text, 'html.parser')
    pages = soup.find_all("a", {"class": 'navPages'})
    return max( [int(p.string) for p in pages] )


def get_all_post_id(cookies, uid):
    post_ids = []

    #first we get how many pages there are (sadly url uses offset and not page :/)
    lastpage = get_last_page(cookies, uid)

    for page, i in enumerate(range(0, lastpage*60, 60), start=1): #basicly for each page as there is 60 posts per page
    #yes we do re-request the first page but shush i'm too lazy to optimize
        print(f"Fetching posts on page {page}/{lastpage}", end="\r", flush=True)
        r = requests.get(base_url.format(uid=uid, offset=i), cookies=cookies)
        soup = BeautifulSoup(r.text, 'html.parser')
        posts = soup.find_all("a", href=True)
        posts = [reg.search(p['href']) for p in posts]
        posts = [p.group(1) for p in posts if p is not None]
        posts = list(set(posts)) #removes dupes as every post ID is present twice in the list
        post_ids += posts #we add the newly found post ids
    
    #We have all posts ids, we return
    return post_ids
        
def download_post(cookies, pid, failcounter=1):
    while True:
        try:
            r = requests.get(base_image_url.format(pid=pid), cookies=cookies, timeout=100)
        except requests.exceptions.Timeout:
            print(f"Downloading post {pid} timed out, trying again...")
            continue
        except requests.exceptions.RequestException:
            print(f"Downloading post {pid} raised some network error, trying again...")
        break
    soup = BeautifulSoup(r.text, 'html.parser')

    try:
        #confusing mess, just know pointer is used to go down the html tree and that everything is VERY hardcoded
        pointer = soup.find_all("tr", {"class": 'catbg'})[0]
        title = pointer.td.string
        pointer = pointer.find_next_sibling("tr")
        img = pointer.td.a.img["src"]
        pointer = pointer.find_next_sibling("tr").find_next_sibling("tr")
        pointer = pointer.td

        # for i in pointer.children:
        #     print(i)
        #     print("-------------\n\n")

        #info_string = pointer.children
        #collections.deque(itertools.islice(info_string, 2)) #advance the iterator 2 times 
        pointer = pointer.br.next_element.next_element
        description = pointer.string.strip()
        pointer = pointer.find_next_sibling("hr").find_next_sibling("br").next_element
        views = pointer.string.replace("Views: ", "")
        pointer = pointer.next_element.next_element
        favorites = pointer.string.replace("Total Favorities: ", "")
        pointer = pointer.find_next_sibling("br").next_element
        keywords = []
        while True: #iterate over the keywords
            pointer = pointer.next_element
            if pointer.name == "a": #found a keyword
                keywords.append(pointer.string)
            elif pointer.name == "br": #we reached the end of keywords, exit
                break

        pointer = pointer.find_next_sibling().find_next_sibling().next_element.next_element
        datestr = pointer.string.strip()
        pointer = pointer.next_sibling.next_sibling.next_sibling
        rating = pointer.string.replace("Rating: ", "")

        # imgs = soup.find_all("img")
        # img = next(i for i in imgs if not "thumb_" == i['src'])
        file_extension = os.path.splitext(urlparse(img).path)[1]

        #download the pic
        while True:
            try:
                r = requests.get(img, stream=True, timeout=500)
            except requests.exceptions.Timeout:
                print(f"Downloading image for post {pid} timed out, trying again...")
                continue
            break
        with open(f"{download_dir}/{pid}{file_extension}", "wb+") as f:
            f.write(r.content)
        write_metadata_file(pid, 
            title,
            views, 
            datestr, 
            rating, 
            description, 
            keywords, 
            favorites) 
    except Exception as e: #global error handler, doesn't include network error
        if failcounter > 20:
            print(f"Error while processing post {pid} over 20 times, skipping it")
            return
        print(f"Error while processing post {pid}, retrying it from scratch in {round(failcounter*failcounter/2)} seconds")
        print(e)
        try:
            for i in reversed(range(1, round(failcounter*failcounter/2 +1))): #scales up nicely
                print(f"{i} seconds left, press ctrl + c to skip the countdown", end="\r", flush=True)
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        print("Retrying...                                                ", end="\r", flush=True)
        download_post(cookies, pid, failcounter+1)

    

def write_metadata_file(pid, title, views, datestr, rating, description, keywords, favorites):
    try:
        rating = int(rating)
    except ValueError: #says 'This picture has not been rated yet.' if 0
        rating = 0
    data = {
        'id': int(pid),
        'title': title,
        "views": int(views),
        "date": datestr,
        "rating": int(rating),
        "description": description,
        "keywords": keywords,
        "favorites": favorites
    }

    with open(f'{download_dir}/{pid}.json', "w+") as f:
        f.write(json.dumps(data, indent=4))


def fast_mode(cookies, uid): #download all pics without metadata
    lastpage = get_last_page(cookies, uid)

    for page, i in enumerate(range(0, lastpage*60, 60), start=1): #basicly for each page as there is 60 posts per page
        print(f"Downloading posts on page {page}/{lastpage}")
        r = requests.get(base_url.format(uid=uid, offset=i), cookies=cookies)
        soup = BeautifulSoup(r.text, 'html.parser')
        posts = soup.find_all("td", {'align': 'center'})
        for p in posts:
            try:
                p["colspan"] #means we reached the last TD, and it's not a post
                break
            except KeyError:
                pid = reg.search(p.find_all("a", href=True)[0]['href']).group(1) #basicly get id from first href link
                print(f"Downloading post {pid}", end="\r", flush=True)
                file_url = p.img['src'].replace("thumb_", "") #get full res from thumb
                file_extension = os.path.splitext(urlparse(file_url).path)[1]

                #download the pic
                r = requests.get(file_url, stream=True)
                with open(f"{download_dir}/{pid}{file_extension}", "wb+") as f:
                    f.write(r.content)

                #write metadata
                smalltext = p.span
                for br in smalltext.find_all("br"):
                    br.replace_with("\n")
                smalltextsplit = smalltext.text.split("\n")
                write_metadata_file(pid, #post id 
                    p.p.string, #title
                    smalltextsplit[0].replace("Views: ", ""), #views
                    smalltextsplit[2].replace("Date: ", ""), #date
                    smalltextsplit[3].replace("Rating: ", ""), #rating 
                    "No description as this was scrapped with fast mode", 
                    "No keywords as this was scrapped with fast mode", 
                    "No favorites as this was scrapped with fast mode")

    

username = input("Enter your username\n> ")
password = input("Enter your password\n> ")
uid = input("Enter the user's id\n> ")
print("Use fast mode? (goes faster but doesn't download the keywords or description)")
fm = ""
while not fm in ("y", "n", "yes", "no"):
    fm = input("[Y/N] > ").lower()
if fm in ("y", "yes"):
    print("Fast mode enabled")
    do_fast_mode = True
else:
    print("Fast mode disabled")
    do_fast_mode = False

#we make our download folder using the current work dir
download_dir = os.getcwd() + f"/{uid}"
print()
try:
    os.mkdir(uid)
    print(f"Downloading files to {download_dir}")
    do_overwrite = False #just in case
except FileExistsError:
    if not os.listdir(download_dir): #if dir is empty
        print(f"Downloading files to {download_dir}")
        do_overwrite = False #just in case
    else:
        print(f"{download_dir} is already used")
        print("Should we overwrite existing files? (saying no will just skip them)")
        ow = ""
        while not ow in ("y", "n", "yes", "no"):
            ow = input("[Y/N] > ").lower()
        if ow in ("y", "yes"):
            print("Overwrite enabled")
            do_overwrite = True
        else:
            print("Overwrite disabled")
            do_overwrite = False

print("Logging in...")
cookies = get_cookies(username, password)
#should probably check if properly logged in

if do_fast_mode:
    fast_mode(cookies, uid)
else:
    print("Fetching posts to download...")
    post_ids = get_all_post_id(cookies, uid)
    #filter the posts to not redownload
    if not do_overwrite:
        post_ids = [p for p in post_ids if not os.path.exists(f"{download_dir}/{p}.json")] #we check if the json exist
        #this is perfect since we write the json file at the very end, so it won't skip if the pic download crashed, only if the pic was fully downloaded

    #we have all the post ids, time to get downloading
    print(f"Found {str(len(post_ids))} posts to download")
    for i, p in enumerate(sorted(post_ids, key=int, reverse=True), start=1):
        print(f"Downloading post {p} ({i}/{len(post_ids)})", end="\r", flush=True)
        download_post(cookies, p)
print("Done!")
input()
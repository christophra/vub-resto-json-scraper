#!/usr/bin/env python

###########################
# Imports
###########################

import io
import os
import string
import json
import logging
import datetime
import requests
import lxml.html
from lxml.cssselect import CSSSelector
from multiprocessing.dummy import Pool as ThreadPool

###########################
# Configuration
###########################

# Path where the JSONs will get written. Permissions are your job.
SAVE_PATH = '/var/www/ssl/files/vub-resto/'
#SAVE_PATH = '/home/chris/Software/utils/resto/'
#SAVE_PATH = './'

# Urls of the pages that will get parsed
URL = 'https://student.vub.be/en/menu-vub-student-restaurant'


# Mapping of colors for the menus.
DEFAULT_COLOR = '#f0eb93'  # very light yellow
COLOR_MAPPING = {
    'soep': '#fdb85b',  # yellow
    'soup': '#fdb85b',  # yellow
    'menu 1': '#68b6f3',  # blue
    'dag menu': '#68b6f3',  # blue
    'dagmenu': '#68b6f3',  # blue
    'health': '#ff9861',  # orange
    'vis': '#ff9861',  # orange
    'fish': '#ff9861',  # orange
    'menu 2': '#cc93d5',  # purple
    'meals of the world': '#cc93d5',  # purple
    'fairtrade': '#cc93d5',  # purple
    'fairtrade menu': '#cc93d5',  # purple
    'veggie': '#87b164',  # green
    'veggiedag': '#87b164',  # green
    'pasta': '#de694a',  # red
    'pasta bar': '#de694a',  # red
    'wok': '#6c4c42',  # brown
}

CAMPUS_NAMES = ['etterbeek','jette']

###########################
# Basic parsing functions
###########################

def normalize_text(text):
    r"""Remove special characters from text, preparing it for JSON.
    """
    return text.replace(u'\xa0', u' ').strip()

def check_title(line):
    r"""Check whether line matches a title for a restaurant's week menu.
    Return campus,language or None.
    """
    # verify format
    line = line.lower()
    has_menu  = ('menu' in line)
    has_campus = any([p in line for p in CAMPUS_NAMES])
    if not (has_menu and has_campus):
        return None
    
    campus = 'unknown'
    # determine place
    for c in CAMPUS_NAMES:
        if c in line: campus = c
    
    # determine language
    language = 'unknown'
    if 'week menu' in line:
        language = 'en'
    if 'weekmenu' in line:
        language = 'nl' 
        
    return '{0}.{1}'.format(campus,language)

def check_date(line):
    r"""Check whether date matches D(D).M(M).(YY)YY(:).
    Return corresponding datetime.date or None.
    """
    line = line.rstrip(':') # remove possible trailing colon
    parts = line.split('.') # split by separator
    parts = list(filter(lambda s:s.isdigit(), parts)) # remove any that are not numbers
    triplet = len(parts)==3
    if not triplet:
        return None
    dd, mm, yyyy = tuple(list(map(int, parts)))
    if (yyyy%1000)<18:
        return None
    yyyy = 2000 + (yyyy%1000)
    return datetime.date(yyyy, mm, dd)

def parse_menu(m):
    r"""Parse a single menu entry of the format Menu name: Dish name.
    Return {'name':'Menu name',
            'dish':'Dish name',
            'color':color code}
            or None.
    """
    m = m.split(':')

    menu_name = normalize_text(m[0])
    menu_dish = normalize_text(':'.join(m[1:]))

    menu_name = menu_name.replace(' van de week','') # make uniform names
    menu_name = menu_name.replace(' of the week','') # between Etterbeek & Jette


    menu_color = COLOR_MAPPING.get(menu_name.lower(), None)
    if menu_color is None:
        logging.warning("No color found for the menu {0}".format(menu_name))
        menu_color = DEFAULT_COLOR
    return {'name': menu_name,
            'dish': menu_dish,
            'color': menu_color}

###########################
# Combining functions
###########################

def load_and_split(url):
    r"""First step:
    Load page from URL, build the DOM tree,
    and split it by the different week menus it contains.
    """
    data = {}
    
    # Construct CSS selectors
    sel_resto = CSSSelector('div.pg-tab')
    sel_content = CSSSelector('div.rd-content-holder')
    sel_resto_title = CSSSelector('h2')
    
    # Request and build the DOM Tree
    r = requests.get(url)
    tree = lxml.html.fromstring(r.text)
    
    # Iterate over restaurants
    for div in sel_resto(tree):
        # Split into sections
        sections = sel_content(div)
        # First is the title
        resto_title = sel_resto_title(sections[0])[0].text_content()
        # Parse into location.language e.g. etterbeek.nl
        resto_key = check_title(resto_title)
        if resto_key is None:
            logging.exception('Failed to extract restaurant title from {0} at URL {1}'.format(div.text_content(), url))
            continue
        # Store daily menus
        data[resto_key] = sections[1:]
    return data

def parse_restaurant((name, week)):
    r"""Parse the weekly menu for one restaurant.
    """
    data = []
    
    sel_date = CSSSelector('p')
    sel_meals = CSSSelector('ul li')
    
    prev_date = datetime.date(2000,1,1)
    
    for day in week:
        menus = []

        date_string = sel_date(day)[0].text_content()
        date = check_date(date_string)
        if date is not None:
            prev_date = date # store for next iteration
        else:
            # If we couldn't parse the date, we try to use the previous date
            logging.warning("{0} - Failed to parse: date {1}".format(name, date_string))
            try:
                date = prev_date + datetime.timedelta(days=1)
                prev_date = date
            except Exception:
                # If we can't find any date, we'll skip the day
                logging.exception("{0}/{1} - Failed to parse: couldn't derive date from previous dates".format(name, date_string))

        meals = sel_meals(day)
        for m in meals:
            try:
                m = parse_menu(m.text_content())
            except Exception:
                logging.exception("{0}/{1} - Failed to parse: menu {2}".format(name, date_string, m))
            #if m['dish']:
            menus.append(m)

        data.append({'date': str(date), 'menus': menus})
    return name, data

###########################
# Output
###########################

def write_to_json((name, data)):
    filename = name.lower() + '.json'
    with io.open(os.path.join(SAVE_PATH, filename), 'w', encoding='utf8') as f:
        try:
            f.write(unicode(json.dumps(data, ensure_ascii=False)))
        except Exception:
            logging.exception(name + " - Failed to save to json")

###########################
# Main
###########################

def main():
    # Configure the logger
    logging.basicConfig(filename=SAVE_PATH+'menuparser.log', level='WARNING')
    
    # Fetch webpage and split into weekly menus
    content = load_and_split(URL)
    
    # Parse and save the 2 restaurants x 2 languages
    pool = ThreadPool(4)
    parsed = pool.map(parse_restaurant, content.items())
    pool.map(write_to_json, parsed)


if __name__ == "__main__":
    main()


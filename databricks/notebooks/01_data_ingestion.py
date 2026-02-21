# Databricks notebook source
# MAGIC %md
# MAGIC # Script Segmentation Model - Data Ingestion
# MAGIC 
# MAGIC This notebook downloads and ingests data from:
# MAGIC 1. **Cornell Movie Dialogs Corpus** - 220,579 conversational exchanges from 617 movies
# MAGIC 2. **IMSDB (Internet Movie Script Database)** - Full movie scripts with scene structure
# MAGIC 
# MAGIC The combined dataset will be used to train a beat segmentation model.

# COMMAND ----------

# MAGIC %pip install requests beautifulsoup4 lxml tqdm

# COMMAND ----------

import os
import ast
import requests
import zipfile
import json
from pathlib import Path
from bs4 import BeautifulSoup
from tqdm import tqdm
from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, ArrayType

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Cornell Movie Dialogs Corpus

# COMMAND ----------

CORNELL_URL = "http://www.cs.cornell.edu/~cristian/data/cornell_movie_dialogs_corpus.zip"
DATA_PATH = "/dbfs/FileStore/playwright/raw_data"
CORNELL_PATH = f"{DATA_PATH}/cornell_movie_dialogs"

os.makedirs(DATA_PATH, exist_ok=True)
os.makedirs(CORNELL_PATH, exist_ok=True)

# COMMAND ----------

def download_cornell_corpus():
    """Download and extract Cornell Movie Dialogs Corpus."""
    zip_path = f"{DATA_PATH}/cornell_corpus.zip"
    
    if not os.path.exists(f"{CORNELL_PATH}/movie_lines.txt"):
        print("Downloading Cornell Movie Dialogs Corpus...")
        response = requests.get(CORNELL_URL, stream=True)
        
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        print("Extracting...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(DATA_PATH)
        
        print("Cornell corpus downloaded and extracted.")
    else:
        print("Cornell corpus already exists.")

download_cornell_corpus()

# COMMAND ----------

def parse_cornell_lines(filepath):
    """Parse movie_lines.txt from Cornell corpus."""
    lines = []
    with open(filepath, 'r', encoding='iso-8859-1') as f:
        for line in f:
            parts = line.strip().split(' +++$+++ ')
            if len(parts) == 5:
                lines.append({
                    'line_id': parts[0],
                    'character_id': parts[1],
                    'movie_id': parts[2],
                    'character_name': parts[3],
                    'text': parts[4]
                })
    return lines

def parse_cornell_conversations(filepath):
    """Parse movie_conversations.txt from Cornell corpus."""
    conversations = []
    with open(filepath, 'r', encoding='iso-8859-1') as f:
        for line in f:
            parts = line.strip().split(' +++$+++ ')
            if len(parts) == 4:
                line_ids = ast.literal_eval(parts[3])
                conversations.append({
                    'character1_id': parts[0],
                    'character2_id': parts[1],
                    'movie_id': parts[2],
                    'line_ids': line_ids
                })
    return conversations

def parse_cornell_movies(filepath):
    """Parse movie_titles_metadata.txt from Cornell corpus."""
    movies = []
    with open(filepath, 'r', encoding='iso-8859-1') as f:
        for line in f:
            parts = line.strip().split(' +++$+++ ')
            if len(parts) >= 5:
                movies.append({
                    'movie_id': parts[0],
                    'title': parts[1],
                    'year': parts[2],
                    'imdb_rating': parts[3],
                    'genres': ast.literal_eval(parts[5]) if len(parts) > 5 else []
                })
    return movies

# COMMAND ----------

cornell_base = f"{DATA_PATH}/cornell movie-dialogs corpus"

lines_data = parse_cornell_lines(f"{cornell_base}/movie_lines.txt")
conversations_data = parse_cornell_conversations(f"{cornell_base}/movie_conversations.txt")
movies_data = parse_cornell_movies(f"{cornell_base}/movie_titles_metadata.txt")

print(f"Loaded {len(lines_data)} lines")
print(f"Loaded {len(conversations_data)} conversations")
print(f"Loaded {len(movies_data)} movies")

# COMMAND ----------

lines_schema = StructType([
    StructField("line_id", StringType(), True),
    StructField("character_id", StringType(), True),
    StructField("movie_id", StringType(), True),
    StructField("character_name", StringType(), True),
    StructField("text", StringType(), True),
])

df_lines = spark.createDataFrame(lines_data, schema=lines_schema)
df_lines.write.mode("overwrite").saveAsTable("playwright.cornell_lines")

print(f"Saved {df_lines.count()} lines to playwright.cornell_lines")

# COMMAND ----------

movies_schema = StructType([
    StructField("movie_id", StringType(), True),
    StructField("title", StringType(), True),
    StructField("year", StringType(), True),
    StructField("imdb_rating", StringType(), True),
    StructField("genres", ArrayType(StringType()), True),
])

df_movies = spark.createDataFrame(movies_data, schema=movies_schema)
df_movies.write.mode("overwrite").saveAsTable("playwright.cornell_movies")

print(f"Saved {df_movies.count()} movies to playwright.cornell_movies")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. IMSDB Scripts

# COMMAND ----------

IMSDB_BASE_URL = "https://imsdb.com"
IMSDB_PATH = f"{DATA_PATH}/imsdb"
os.makedirs(IMSDB_PATH, exist_ok=True)

# COMMAND ----------

def get_imsdb_script_list():
    """Get list of all available scripts from IMSDB."""
    all_scripts_url = f"{IMSDB_BASE_URL}/all-scripts.html"
    
    response = requests.get(all_scripts_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    scripts = []
    for link in soup.find_all('a'):
        href = link.get('href', '')
        if '/Movie Scripts/' in href:
            title = link.text.strip()
            if title:
                script_name = href.split('/')[-1].replace(' Script.html', '')
                scripts.append({
                    'title': title,
                    'url': f"{IMSDB_BASE_URL}{href}",
                    'script_name': script_name
                })
    
    return scripts

# COMMAND ----------

def download_imsdb_script(script_info):
    """Download a single script from IMSDB."""
    try:
        response = requests.get(script_info['url'], timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        script_link = soup.find('a', href=lambda x: x and '/scripts/' in x.lower())
        if not script_link:
            return None
        
        script_url = f"{IMSDB_BASE_URL}{script_link['href']}"
        script_response = requests.get(script_url, timeout=30)
        script_soup = BeautifulSoup(script_response.text, 'html.parser')
        
        pre_tag = script_soup.find('pre')
        if pre_tag:
            script_text = pre_tag.get_text()
            return {
                'title': script_info['title'],
                'script_name': script_info['script_name'],
                'text': script_text,
                'url': script_info['url']
            }
    except Exception as e:
        print(f"Error downloading {script_info['title']}: {e}")
    
    return None

# COMMAND ----------

script_list = get_imsdb_script_list()
print(f"Found {len(script_list)} scripts on IMSDB")

downloaded_scripts = []
sample_size = min(200, len(script_list))

for script_info in tqdm(script_list[:sample_size], desc="Downloading scripts"):
    script_data = download_imsdb_script(script_info)
    if script_data:
        downloaded_scripts.append(script_data)

print(f"Successfully downloaded {len(downloaded_scripts)} scripts")

# COMMAND ----------

imsdb_schema = StructType([
    StructField("title", StringType(), True),
    StructField("script_name", StringType(), True),
    StructField("text", StringType(), True),
    StructField("url", StringType(), True),
])

df_imsdb = spark.createDataFrame(downloaded_scripts, schema=imsdb_schema)
df_imsdb.write.mode("overwrite").saveAsTable("playwright.imsdb_scripts")

print(f"Saved {df_imsdb.count()} scripts to playwright.imsdb_scripts")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Data Summary

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE DATABASE IF NOT EXISTS playwright;

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT 'Cornell Lines' as source, COUNT(*) as count FROM playwright.cornell_lines
# MAGIC UNION ALL
# MAGIC SELECT 'Cornell Movies' as source, COUNT(*) as count FROM playwright.cornell_movies
# MAGIC UNION ALL
# MAGIC SELECT 'IMSDB Scripts' as source, COUNT(*) as count FROM playwright.imsdb_scripts

# COMMAND ----------

# MAGIC %md
# MAGIC ## Next Steps
# MAGIC 
# MAGIC Data has been ingested into Delta tables:
# MAGIC - `playwright.cornell_lines` - Individual dialogue lines
# MAGIC - `playwright.cornell_movies` - Movie metadata
# MAGIC - `playwright.imsdb_scripts` - Full movie scripts
# MAGIC 
# MAGIC Proceed to **02_data_preprocessing** to:
# MAGIC 1. Parse scene boundaries from IMSDB scripts
# MAGIC 2. Create beat-level annotations
# MAGIC 3. Build training dataset for segmentation model

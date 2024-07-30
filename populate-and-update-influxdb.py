import berserk
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
from influxdb_client import InfluxDBClient, Point, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pytz
import time
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
import requests
import argparse

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Lichess API setup
lichess_token = os.getenv('LICHESS_TOKEN')
lichess_username = os.getenv('LICHESS_USERNAME')
client = berserk.Client(berserk.TokenSession(lichess_token))

# InfluxDB setup
influx_url = "http://influxdb:8086"
influx_token = os.getenv('INFLUXDB_INIT_PASSWORD')
org = os.getenv('INFLUXDB_INIT_ORG')
bucket = os.getenv('INFLUXDB_INIT_BUCKET')

influx_client = InfluxDBClient(url=influx_url, token=influx_token, org=org)
write_options = WriteOptions(batch_size=500, flush_interval=10_000, jitter_interval=2_000, retry_interval=5_000)
write_api = influx_client.write_api(write_options=write_options)
query_api = influx_client.query_api()

def get_timestamp(created_at):
    if isinstance(created_at, datetime):
        return created_at.replace(tzinfo=pytz.UTC)
    elif isinstance(created_at, (int, float)):
        return datetime.fromtimestamp(created_at / 1000, pytz.UTC)
    else:
        raise ValueError(f"Unexpected type for createdAt: {type(created_at)}")

def is_bucket_empty():
    query = f'''
    from(bucket:"{bucket}")
        |> range(start: -1y)
        |> limit(n: 1)
    '''
    result = query_api.query(query=query, org=org)
    return len(result) == 0

def get_last_update_time():
    query = f'''
    from(bucket:"{bucket}")
        |> range(start: -30d)
        |> filter(fn: (r) => r._measurement == "lichess_games" or r._measurement == "lichess_rating_history" or r._measurement == "lichess_perf_stats" or r._measurement == "lichess_account")
        |> last()
    '''
    result = query_api.query(query=query, org=org)
    if result and len(result) > 0:
        return max(record.values['_time'] for table in result for record in table.records)
    else:
        return datetime.now(pytz.UTC) - timedelta(days=30)  # Default to 30 days ago if no data

@retry(retry=retry_if_exception_type((requests.exceptions.RequestException, berserk.exceptions.ResponseError)), 
       stop=stop_after_attempt(5), wait=wait_fixed(10))
def retry_fetch_new_games(username, last_update):
    return list(client.games.export_by_player(username, since=last_update))

def fetch_and_store_all_data():
    username = lichess_username
    try:
        # Fetch rating history
        rating_history = client.users.get_rating_history(username)
        points = [
            Point("lichess_rating_history")
            .tag("username", username)
            .tag("perf", perf['name'])
            .field("rating", entry[3])
            .time(datetime(year=entry[0], month=entry[1]+1, day=entry[2], tzinfo=pytz.UTC))
            for perf in rating_history
            for entry in perf['points']
        ]
        write_api.write(bucket=bucket, org=org, record=points)
        logger.info("Rating history written to InfluxDB.")

        # Fetch user profile data
        user_data = client.users.get_public_data(username)
        for perf, stats in user_data['perfs'].items():
            point = Point("lichess_perf_stats") \
                .tag("username", username) \
                .tag("perf", perf) \
                .field("games", stats.get('games', 0)) \
                .field("rating", stats.get('rating', 0)) \
                .field("rd", stats.get('rd', 0)) \
                .field("prog", stats.get('prog', 0)) \
                .time(datetime.utcnow().replace(tzinfo=pytz.UTC))
            write_api.write(bucket=bucket, org=org, record=point)
        print("Performance statistics written to InfluxDB.")

        # Fetch all games
        games = client.games.export_by_player(username)
        game_count = 0
        points = []

        points = [
            Point("lichess_games")
            .tag("username", username)
            .tag("variant", game['variant'])
            .tag("speed", game['speed'])
            .field("rated", game['rated'])
            .field("status", game['status'])
            .field("winner", game.get('winner', ''))
            .field("moves", game.get('moves', ''))
            .field("white_rating", game['players']['white'].get('rating', 0))
            .field("black_rating", game['players']['black'].get('rating', 0))
            .time(get_timestamp(game['createdAt']))
            for game in games
        ]
        for i in range(0, len(points), 1000):
            write_api.write(bucket=bucket, org=org, record=points[i:i+1000])
            logger.info(f"{i + 1000 if i + 1000 < len(points) else len(points)} games written to InfluxDB.")
            if (i // 1000 + 1) % 3 == 0:
                time.sleep(60)  # Sleep for a minute every 300 games
        logger.info(f"All {len(points)} games written to InfluxDB.")

        print(f"All {game_count} games written to InfluxDB.")

        # Fetch account data
        account = client.account.get()
        point = Point("lichess_account") \
            .tag("username", username) \
            .field("country", account.get('country', '')) \
            .field("language", account.get('language', '')) \
            .field("title", account.get('title', '')) \
            .field("is_streamer", account.get('streamer', False)) \
            .field("created_at", int(get_timestamp(account.get('createdAt', 0)).timestamp())) \
            .field("seen_at", int(get_timestamp(account.get('seenAt', 0)).timestamp())) \
            .field("playing_time", account.get('playTime', {}).get('total', 0)) \
            .time(datetime.utcnow().replace(tzinfo=pytz.UTC))
        write_api.write(bucket=bucket, org=org, record=point)
        print("Account data written to InfluxDB.")

        print(f"All data for {username} written to InfluxDB successfully.")
    except Exception as e:
        print(f"Error occurred: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        write_api.close()  # Properly close the write API

def fetch_and_store_new_data():
    username = os.getenv('LICHESS_USERNAME')
    last_update = get_last_update_time()
    
    print(f"Checking for new data since {last_update}...")
    
    try:
        # Fetch new games
        new_games = retry_fetch_new_games(username, last_update)
        game_count = 0
        points = []

        points = [
            Point("lichess_games")
            .tag("username", username)
            .tag("game_id", game['id'])
            .tag("variant", game['variant'])
            .tag("speed", game['speed'])
            .field("rated", game['rated'])
            .field("status", game['status'])
            .field("winner", game.get('winner', ''))
            .field("moves", game.get('moves', ''))
            .field("white_rating", game['players']['white'].get('rating', 0))
            .field("black_rating", game['players']['black'].get('rating', 0))
            .time(get_timestamp(game['createdAt']))
            for game in new_games
            if get_timestamp(game['createdAt']) > last_update
        ]
        for i in range(0, len(points), 1000):
            write_api.write(bucket=bucket, org=org, record=points[i:i+1000])
            logger.info(f"Data for {i + 1000 if i + 1000 < len(points) else len(points)} new games synced to database.")

            # Update rating history
            rating_history = client.users.get_rating_history(username)
            points = [
                Point("lichess_rating_history")
                .tag("username", username)
                .tag("perf", perf['name'])
                .field("rating", latest_entry[3])
                .time(datetime(year=latest_entry[0], month=latest_entry[1]+1, day=latest_entry[2], tzinfo=pytz.UTC))
                for perf in rating_history
                if perf['points']
                for latest_entry in [max(perf['points'], key=lambda x: datetime(year=x[0], month=x[1]+1, day=x[2], tzinfo=pytz.UTC))]
                if datetime(year=latest_entry[0], month=latest_entry[1]+1, day=latest_entry[2], tzinfo=pytz.UTC) > last_update
            ]
            write_api.write(bucket=bucket, org=org, record=points)
            logger.info("Rating history updated in InfluxDB.")

            # Update performance statistics
            user_data = client.users.get_public_data(username)
            points = [
                Point("lichess_perf_stats")
                .tag("username", username)
                .tag("perf", perf)
                .field("games", stats.get('games', 0))
                .field("rating", stats.get('rating', 0))
                .field("rd", stats.get('rd', 0))
                .field("prog", stats.get('prog', 0))
                .time(datetime.utcnow().replace(tzinfo=pytz.UTC))
                for perf, stats in user_data['perfs'].items()
            ]
            write_api.write(bucket=bucket, org=org, record=points)
            logger.info("Performance statistics updated in InfluxDB.")

            # Update account data
            account = client.account.get()
            point = Point("lichess_account") \
                .tag("username", username) \
                .field("country", account.get('country', '')) \
                .field("language", account.get('language', '')) \
                .field("title", account.get('title', '')) \
                .field("is_streamer", account.get('streamer', False)) \
                .field("created_at", int(get_timestamp(account.get('createdAt', 0)).timestamp())) \
                .field("seen_at", int(get_timestamp(account.get('seenAt', 0)).timestamp())) \
                .field("playing_time", account.get('playTime', {}).get('total', 0)) \
                .time(datetime.utcnow().replace(tzinfo=pytz.UTC))
            write_api.write(bucket=bucket, org=org, record=point)
            print("Account data updated in InfluxDB.")

        logger.info("Account data updated in InfluxDB.")
        if points:
            logger.info("New games found and updated.")
            return True
        else:
            logger.info("No new games to update.")
            return False
    except Exception as e:
        logger.error(f"Error occurred: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        write_api.close()  # Properly close the write API

def delete_all_data():
    logger.info("Deleting all data from the InfluxDB bucket...")
    delete_api = influx_client.delete_api()
    start = "1970-01-01T00:00:00Z"
    stop = datetime.now(pytz.UTC).isoformat()
    delete_api.delete(start, stop, f'_measurement="{bucket}"', bucket=bucket, org=org)
    logger.info("All data has been successfully deleted from the bucket.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lichess data fetcher and InfluxDB updater")
    parser.add_argument("--delete", action="store_true", help="Delete all data from InfluxDB before fetching")
    args = parser.parse_args()

    update_interval = 300  # 15 minutes



    if is_bucket_empty():
        logger.info("Bucket is empty. Fetching all data for the first time.")
        fetch_and_store_all_data()  # Perform the initial data load

    while True:
        if fetch_and_store_new_data():
            logger.info(f"Data updated. Sleeping for {update_interval} seconds.")
        else:
            logger.info(f"No new data. Sleeping for {update_interval} seconds.")

        time.sleep(update_interval)


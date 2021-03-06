#!/usr/bin/env python3

# TODO: Figure out what to do with pids/processes as you probably don't need both

import logging
from logging.handlers import RotatingFileHandler
import argparse
import sys
import os
import youtube_dl
import yaml
from multiprocessing import Manager
from multiprocessing import Process
import time
from datetime import datetime, timezone
import requests
import signal
import platform
import shutil
from pathlib import Path
from streamlink import Streamlink, StreamError, PluginError, NoPluginError

# set up manager functions
mgr = Manager()
pids = mgr.dict()
processes = []
logger = logging.getLogger()
movepath = ""


class YTDLLogger(object):
    """
    Just a class to shut YTDL up
    """
    def debug(self, msg):
        return

    def warning(self, msg):
        return

    def error(self, msg):
        return


def main(argv):
    """
    The main function that does the stuff
    """
    global logger
    global movepath

    # set up signal handler
    signal.signal(signal.SIGTERM, receive_signal)
    signal.signal(signal.SIGINT, receive_signal)

    # set up arg parser and arguments
    parser = argparse.ArgumentParser(prog='python streamdl.py',
                                     description='Monitor and Download Streams from a Variety of Websites')
    parser.add_argument('-c', '--config', required=True, help='Config file to use')
    parser.add_argument('-l', '--logfile', help='Logfile to use (path defaults to working dir)')
    parser.add_argument('-ll', '--loglevel', help='Log level to set (defaults to INFO)')
    parser.add_argument('-o', '--outdir', help='Output file location without trailing slash (defaults to working dir)')
    parser.add_argument('-m', '--movedir', help='Directory to move after download has completed')
    parser.add_argument('-r', '--repeat', help='Time to repetitively check users, in minutes')
    args = parser.parse_args()

    setup_logging(args)

    # check if output dir is specified
    if not args.outdir:
        outdir = os.getcwd() + "/media/"
    else:
        outdir = args.outdir

    # check if movedir is specified
    if args.movedir:
        movepath = args.movedir
    else:
        movepath = outdir

    logger.info("Starting StreamDL...")
    logger.info("Downloading to: {}".format(outdir))
    logger.info("Moving to: {}".format(movepath))

    users = config_reader(args.config)
    logger.info("Users in Config: {}".format(users))
    mass_downloader(users, outdir)

    # check if repeat is specified
    if args.repeat:
        recurse(args.repeat, outdir, config=args.config)


def recurse(repeat, outdir, **kwargs):
    """
    Main recursive function
    """
    global logger

    sleep_time = int(repeat) * 60
    logger.debug("Sleeping for {} Seconds".format(sleep_time))
    # sleep for sleep_time minus process checking sleep time
    for i in range(sleep_time - 10):
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            logger.debug("recurse thread interrupt caught...")
    # always reload config in case local changes are made
    users = config_reader(kwargs.get("config"))
    logger.info("Users in Current Config: {}".format(users))

    mass_downloader(users, outdir)

    recurse(repeat, outdir, **kwargs)


# parse through users and launch downloader if necessary
def mass_downloader(config, outdir):
    """
    Handles the process spawning to download multiple things at once
    """
    global pids
    global processes
    global logger

    for url in config:
        for user in config[url]:
            # set up process for given user
            p = Process(name="{}".format(user), target=download_video, args=(url, user, outdir))
            # check for existing download
            if user in pids:
                logger.debug("Process {} Exists with PID {}".format(user, pids.get(user)))
            else:
                if "twitch" in url:
                    if twitch_validate(url + "/" + user):
                        p.start()
                        pids[user] = p.pid
                        processes.append(p)
                        logger.debug("Process {} Started with PID {}".format(p.name, p.pid))
                else:
                    p.start()
                    pids[user] = p.pid
                    processes.append(p)
                    logger.debug("Process {} Started with PID {}".format(p.name, p.pid))
    time.sleep(5)
    process_cleanup()
    return


def process_cleanup():
    """
    Cleans up processes to prevent zombies and max recursion depth issues
    """
    global pids
    global processes
    global logger

    i = 0
    if len(processes) == 0:
        return

    # remove old zombie threads
    while i < len(processes):
        # if PID is alive
        if processes[i].is_alive():
            i += 1
        # if PID is dead
        else:
            try:
                processes[i].close()
                # don't increment iterator
            except AssertionError:
                logger.debug("Something happened, process {} is not joinable...".format(processes[i]))
                i += 1
            try:
                pids.pop(processes[i].name)
            except KeyError:
                logger.debug("KeyError When Popping {} From PIDs List".format(processes[i].name))
            processes.remove(processes[i])
    time.sleep(5)
    logger.debug("Processes after cleaning: {}".format(processes))

    for x in range(0, len(processes)):
        logger.info("Currently Downloading: {}".format(processes[x].name))
        return


# do the video downloading
def download_video(url, user, outpath):
    """
    Handles downloading the individual videos
    """
    global logger
    global movepath

    # check if URL is valid
    try:
        request = requests.get("https://{}/{}".format(url, user), allow_redirects=False)
        # fail on a bad status code
        if request.status_code >= 400:
            logging.warning("URL Has a Bad Status Code: {}/{}".format(url, user))
            logging.warning("Please check your config!")
            return False
    # fail on connection error
    except:
        logging.warning("Unexpected Error: {}".format(sys.exc_info()[0]))
        logging.warning("Invalid URL: {}/{}".format(url, user))
        logging.warning("Please file a bug report: https://github.com/biodrone/issues/new")
        return True

    # pass opts to YTDL
    # TODO: Add an --exec option to this to trigger the move operation
    ydl_opts = {
        'outtmpl': '{}/{}/{}/{} - {}.%(ext)s'.format(
            outpath.rsplit("/", 1)[0], url.upper().split('.')[0], user, user, datetime.utcnow().date()),
        'quiet': True,
        'logger': YTDLLogger(),
        'postprocessor-args': '-movflags +faststart',
        'progress_hooks': [ytdl_hooks],
    }

    # try to pull video from the given user
    try:
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            ydl.download(["https://{}/{}/".format(url, user)])
    except youtube_dl.utils.DownloadError:
        logger.debug("Download Error, {} is Probably Offline".format(user))
    except KeyboardInterrupt:
        logger.debug("Caught KeyBoardInterrupt...")

    return True


def ytdl_hooks(d):
    global logger
    global movepath

    if d['status'] == 'finished':
        if movepath == "":
            return
        file_tuple = os.path.split(os.path.abspath(d['filename']))
        loc = Path(movepath + file_tuple[0].split("/")[-2] + "/" + file_tuple[0].split("/")[-1])
        # TODO: Can use this to pop elements from a Currently Downloading dict in the future
        # print("Done downloading {}".format(file_tuple[1]))
        loc.mkdir(parents=True, exist_ok=True)
        logger.debug("Moving {} to {}".format(file_tuple[0], loc))
        logger.debug(shutil.move(d['filename'], loc))


def twitch_validate(url):

    streamlink = Streamlink()

    try:
        streams = streamlink.streams(url)
    except NoPluginError:
        logger.info("Streamlink is unable to handle the URL '{0}'".format(url))
        return False
    except PluginError as err:
        logging.info("Plugin error: {0}".format(err))
        return False

    if not streams:
        logger.debug("No streams found on URL '{0}'".format(url))
        return False
    else:
        return True

    # stream = streams['best']
    # streamlink -o test.mp4 --twitch-disable-ads --twitch-disable-reruns --twitch-disable-hosting https://www.twitch.tv/day9tv best


# read config and return users
def config_reader(config_file):
    """
    Reads the YAML config file
    """
    global logger

    # read config
    try:
        with open(config_file, 'r') as stream:
            data_loaded = yaml.safe_load(stream)
    except FileNotFoundError:
        logger.error("File {} Not Found".format(config_file))

    # return the data read from config file
    return data_loaded


def rotating_logger(path, level, fmt):
    """
    Logger for writing to files
    """
    global logger

    logger = logging.getLogger("Rotating Log")
    logger.setLevel(level)

    # log rotates every 1mb for 9 times
    handler = RotatingFileHandler(path, maxBytes=1024000, backupCount=9)
    handler.setLevel(level)
    formatter = logging.Formatter(fmt)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


def stream_logger(level, fmt):
    """
    Logger for writing to stdout (for Docker)
    """
    global logger

    logger = logging.getLogger()
    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter(fmt)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


def setup_logging(args):
    global logger

    log_format = '%(asctime)s %(levelname)s: %(message)s'
    # check if log path is specified
    if not args.logfile:
        logfile = os.getcwd() + '/streamdl.log'
    else:
        if os.path.isdir(args.logfile):
            logfile = args.logfile + "/streamdl.log"
        else:
            logfile = args.logfile

    if args.loglevel:
        log_level = getattr(logging, args.loglevel.upper())
    else:
        log_level = logging.INFO

    if logfile == 'stdout':
        logger = stream_logger(log_level, log_format)
    else:
        logger = rotating_logger(logfile, log_level, log_format)


def receive_signal(signum, frame):
    """
    Catches SIGTERM - Mainly to Address Docker Container Stops
    """
    global logger
    logger.debug('Received SIGTERM... Terminating.')
    kill_pids()
    sys.exit(0)


def kill_pids():
    """
    Kill all the PIDs, Even Currently Running Ones
    """
    global processes
    i = 0

    while i < len(processes):
        processes[i].terminate()
        i += 1


if __name__ == '__main__':
    # do the things
    main(sys.argv)

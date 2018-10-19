#!/usr/bin/python

import logging
import argparse
import sys
import os
import youtube_dl
from datetime import datetime
import yaml
from multiprocessing import Process

LOG_LEVEL = logging.DEBUG
FORMAT = '%(asctime)s %(levelname)s: %(message)s'


def main(argv):
    parser = argparse.ArgumentParser(usage='Download the Current Stream by a Chaturbate User')
    parser.add_argument('-u', '--user', help='Chaturbate User')
    parser.add_argument('-l', '--logpath', help='Logfile to use (defaults to working dir)')
    parser.add_argument('-o', '--outdir', help='Output file location without trailing slash (defaults to working dir)')
    parser.add_argument('-c', '--config', help='Config file to use')

    args = parser.parse_args()

    if not args.logpath:
        logfile = 'chaturdownload.log'
    else:
        logfile = args.logpath
    if not args.outdir:
        outDir = os.getcwd()
    else:
        outDir = args.outdir
    user = args.user

    logging.basicConfig(filename=logfile, level=LOG_LEVEL, format=FORMAT)
    logging.debug("Starting ChaturDownload...")
    logging.debug("Downloading to: {}".format(outDir))

    if args.config:
        users = config_reader(args.config)
        logging.debug("Users in Config: {}".format(users))

        for user in users:
            logging.debug("Downloading From User: {}".format(user))
            p = Process(name="{}".format(user), target=download_video, args=(user, outDir))
            p.start()
    else:
        logging.debug("Downloading From User: {}".format(user))
        download_video(user, outDir)


def config_reader(config_file):

    with open(config_file, 'r') as stream:
        data_loaded = yaml.load(stream)

    return data_loaded['users']


def download_video(user, outpath):
    logging.debug("FUNCTION: Downloading Video...")

    ydl_opts = {
        'outtmpl': '{}/{} - {}.%(ext)s'.format(outpath, user, datetime.now())
    }

    try:
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            ydl.download(["https://www.chaturbate.com/{}/".format(user)])
    except youtube_dl.utils.DownloadError:
        return


if __name__ == '__main__':
    main(sys.argv)

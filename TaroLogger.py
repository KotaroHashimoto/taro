#!/usr/bin/env python3

import Adafruit_DHT
import vcgencmd
import signal
import time
import psutil
from datetime import datetime
import pandas as pd
import numpy as np
import os
from glob import glob
from collections import OrderedDict

MEDIADIR = '../usb/media/motion/'
LOGDIR = '../usb/logs/'
INTERVAL = 60 #[s]
DHT_SENSOR = Adafruit_DHT.DHT22
DHT_PIN = 4

col = ['date', 'time', 'activity', 'temp[*C]', 'humid[%}', 'CPU[*C]', 'CPU[v]', 'CPU[MHz]', 'CPU[%]', 'memory[%]', 'rootfs[%]', 'usb[%]']
series = [pd.Series([np.nan for x in col], index = col) \
          for i in range(round(24 * 60 * 60 / INTERVAL))]
currentIndex = 0
previousDateTime = None
vcmd = vcgencmd.Vcgencmd()


def countMotion(dtFrom, dtTo):

    if not dtFrom:
        return 0, None

    global MEDIADIR
    
    fname2time = OrderedDict()
    oldest = None
    num = 0

    for f in glob(MEDIADIR + '*jpg'):
        timeStamp = datetime.fromtimestamp(os.path.getmtime(f))
        fname2time[f] = timeStamp

        if not oldest:
            oldest = f
        elif timeStamp < fname2time[oldest]:
            oldest = f

        if dtFrom <= timeStamp < dtTo:
            num += 1

    return num, oldest
    

def watch(signum, frame):

    global LOGDIR
    global INTERVAL
    global DHT_SENSOR
    global DHT_PIN
    global col
    global series
    global currentIndex
    global vcmd
    global previousDateTime

    currentDateTime = datetime.now()
    day, tm = currentDateTime.strftime('%Y%m%d-%H%M%S').split('-')

    series[currentIndex][['date', 'time']] = [day, tm]
    series[currentIndex][['humid[%}', 'temp[*C]']] = [round(x, 2) for x in Adafruit_DHT.read_retry(DHT_SENSOR, DHT_PIN)]
    series[currentIndex][['CPU[*C]', 'CPU[v]', 'CPU[MHz]']] = [vcmd.measure_temp(), vcmd.measure_volts('core'), round(vcmd.measure_clock('arm') / 1000000)]
    series[currentIndex][['CPU[%]', 'memory[%]', 'rootfs[%]', 'usb[%]']] = [psutil.cpu_percent(interval = 1), psutil.virtual_memory().percent, psutil.disk_usage('/').percent, psutil.disk_usage('/home/pi/usb').percent]
    series[currentIndex]['activity'], oldestJPG = countMotion(previousDateTime, currentDateTime)
    
    if 90 < series[currentIndex]['usb[%]'] and oldestJPG:
        os.remove(oldestJPG)
        print(oldestJPG, 'deleted due to free space shortage.')
        
    if 95 < series[currentIndex]['usb[%]']:
        fname = min(glob(LOGDIR + '20*.csv'))
        os.remove(fname)
        print(fname, 'deleted due to free space shortage.')

    df = pd.DataFrame([y for y in \
                       [x for x in series if not pd.isnull(x['date'])] \
                       if y['date'] == day]) \
           .sort_values(by = 'time', ascending = False)
    
    df.to_csv(LOGDIR + day + '.csv', encoding = 'utf-8', index = False)
    print(day + '.csv dumped with', len(df), 'records (' + tm[:2] + ':' + tm[2:4] + ':' + tm[4:] + ')')
    print(series[currentIndex])

    currentIndex = (currentIndex + 1) % len(series)
    previousDateTime = currentDateTime


if __name__ == '__main__':

    signal.signal(signal.SIGALRM, watch)
    signal.setitimer(signal.ITIMER_REAL, INTERVAL, INTERVAL)
    
    while True:
        time.sleep(86400)

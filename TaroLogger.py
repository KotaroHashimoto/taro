#!/usr/bin/env python3

import Adafruit_DHT
import vcgencmd
import time
import psutil
from datetime import datetime
import pandas as pd
import numpy as np
import os
from glob import glob

LOGDIR = '../usb/logs/'

INTERVAL = 60 #[s]
DHT_SENSOR = Adafruit_DHT.DHT22
DHT_PIN = 4
vcmd = vcgencmd.Vcgencmd()

col = ['date', 'time', 'temp[*C]', 'humid[%}', 'CPU[*C]', 'CPU[v]', 'CPU[MHz]', 'CPU[%]', 'memory[%]', 'rootfs[%]', 'usb[%]']
series = [pd.Series([np.nan for x in col], index = col) \
          for i in range(round(24 * 60 * 60 / INTERVAL))]
currentIndex = 0

while True:

    day, tm = datetime.now().strftime('%Y%m%d-%H%M%S').split('-')

    series[currentIndex][['date', 'time']] = [day, tm]
    series[currentIndex][['humid[%}', 'temp[*C]']] = [round(x, 2) for x in Adafruit_DHT.read_retry(DHT_SENSOR, DHT_PIN)]
    series[currentIndex][['CPU[*C]', 'CPU[v]', 'CPU[MHz]']] = [vcmd.measure_temp(), vcmd.measure_volts('core'), round(vcmd.measure_clock('arm') / 1000000)]
    series[currentIndex][['CPU[%]', 'memory[%]', 'rootfs[%]', 'usb[%]']] = [psutil.cpu_percent(interval = 1), psutil.virtual_memory().percent, psutil.disk_usage('/').percent, psutil.disk_usage('/home/pi/usb').percent]

    if 95 < series[currentIndex]['usb[%]']:
        fname = min(glob(LOGDIR + '20*.csv'))
        os.remove(fname)
        print(fname, 'has deleted due to free space shortage.')

    df = pd.DataFrame([y for y in \
                       [x for x in series if not pd.isnull(x['date'])] \
                       if y['date'] == day]) \
           .sort_values(by = 'time', ascending = False)
    
    df.to_csv(LOGDIR + day + '.csv', encoding = 'utf-8', index = False)
    print(day + '.csv has dumped with', len(df), 'records (' + tm[:2] + ':' + tm[2:4] + ':' + tm[4:] + ')')
    print(series[currentIndex])

    time.sleep(INTERVAL)
    currentIndex = (currentIndex + 1) % len(series)

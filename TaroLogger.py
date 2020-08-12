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
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from slack import WebClient
from slack import RTMClient
from slack.errors import SlackApiError
import logging
import urllib
logging.basicConfig(level = logging.INFO)

MEDIADIR = '../usb/media/motion/'
LOGDIR = '../usb/logs/'
INTERVAL = 60 #[s]
DHT_SENSOR = Adafruit_DHT.DHT22
DHT_PIN = 4

col = ['date', 'time', 'activity', 'temp[*C]', 'humid[%]', 'CPU[*C]', 'CPU[v]', 'CPU[MHz]', 'CPU[%]', 'memory[%]', 'rootfs[%]', 'usb[%]']
series = [pd.Series([np.nan for x in col], index = col) \
          for i in range(round(24 * 60 * 60 / INTERVAL))]
currentIndex = 0
previousDateTime = None
activity = 0
vcmd = vcgencmd.Vcgencmd()

lastMoves = OrderedDict()
lastMoveIndex = [x for x in range(5)]


def countMotion(dtFrom, dtTo):

    if not dtFrom:
        return 0, None, []

    global MEDIADIR
    
    fname2time = OrderedDict()
    oldest = None
    num = 0
    recentFiles = []

    for f in glob(MEDIADIR + '*jpg'):
        timeStamp = datetime.fromtimestamp(os.path.getmtime(f))
        fname2time[f] = timeStamp

        if not oldest:
            oldest = f
        elif timeStamp < fname2time[oldest]:
            oldest = f

        if dtFrom <= timeStamp:
            num += 1
            recentFiles.append(f)

    return num, oldest, recentFiles


def drawChart(df):

    df = df.sort_values(by = ['date', 'time']).reset_index(drop = True)
    xval = df.index

    n = len(df.index)
    if n <= 12:
        hm = [x[:2] + ':' + x[2:4] for x in df['time']]
    elif n <= 60:
        hm = [x[:2] + ':' + x[2:4] if x[3] in '05' else '' for x in df['time']]
    elif n <= 120:
        hm = [x[:2] + ':' + x[2:4] if x[3] == '0' else '' for x in df['time']]
    elif n <= 360:
        hm = [x[:2] + ':' + x[2:4] if x[2:4] in ('00', '30') else '' for x in df['time']]
    elif n <= 720:
        hm = [x[:2] + ':' + x[2:4] if x[2:4] == '00' else '' for x in df['time']]
    else:
        hm = [x[:2] + ':' + x[2:4] if (x[2:4] == '00' and int(x[1]) % 2 == 0) else '' for x in df['time']]
        
    fig = plt.figure(figsize = (16, 9))
    ax1 = fig.add_subplot(111)
    yval = [float(x) for x in df['temp[*C]']]
    if 5 < len(yval):
        for i in range(5, len(yval)):
            average = np.average(yval[i - 5: i])
            if yval[i] < 0.5 * average or 1.5 * average < yval[i]:
                yval[i] = average
                
    ln1 = ax1.plot(xval, yval, 'C0',label = 'Temperature [*C]')

    ax2 = ax1.twinx()
    ln2 = ax2.plot(xval, [int(x) for x in df['activity']], 'C1', label = 'TaroImo Activity [/minute]')

    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc = 'lower right')

    ax1.set_xlabel('Time')
    ax1.set_ylabel('Temperature [*C]')
    ax2.set_ylabel('TaroImo Activity [/minute]')

    ax1.set_title('Temperature and TaroImo Activity')
    ax1.set_xticks(df.index)
    ax1.set_xticklabels(hm, rotation = 40) 
    plt.savefig(LOGDIR + 'Temperature.png')
    plt.close()
    
    fig = plt.figure(figsize = (16, 9))
    ax1 = fig.add_subplot(111)
    yval = [float(x) for x in df['temp[*C]']]
    if 5 < len(yval):
        for i in range(5, len(yval)):
            average = np.average(yval[i - 5: i])
            if yval[i] < 0.5 * average or 1.5 * average < yval[i]:
                yval[i] = average
                
    ln1 = ax1.plot(xval, yval, 'C0',label = 'Temperature [*C]')
    
    ax2 = ax1.twinx()
    yval = [float(x) for x in df['humid[%]']]
    if 5 < len(yval):
        for i in range(5, len(yval)):
            average = np.average(yval[i - 5: i])
            if yval[i] < 0.5 * average or 1.5 * average < yval[i]:
                yval[i] = average
                
    ln2 = ax2.plot(xval, yval, 'C1', label = 'Humidity [%]')

    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc = 'lower right')

    ax1.set_xlabel('Time')
    ax1.set_ylabel('Temperature [*C]')
    ax2.set_ylabel('Humidity [%]')

    ax1.set_title('Temperature and Humidity')
    ax1.set_xticks(df.index)
    ax1.set_xticklabels(hm, rotation = 40) 
    plt.savefig(LOGDIR + 'Humidity.png')
    plt.close()

    
def getLastNImages(addChart, addImage, n):

    global MEDIADIR
    global LOGDIR
    time2fname = OrderedDict()

    for f in glob(MEDIADIR + '*jpg'):
        timeStamp = datetime.fromtimestamp(os.path.getmtime(f))
        time2fname[timeStamp] = f

    files = []
    if addChart:
        for fname in ('Temperature', 'Humidity'):
            if os.path.exists(LOGDIR + fname + '.png'):
                files.append(LOGDIR + fname + '.png')

    if addImage:
        for timeStamp, f in sorted(time2fname.items(), reverse = True):
            files.append(f)
            if n <= len(files):
                break

    return files


def sendMail(sbj, body):

    try:
        os.system('python3 mail.py \"yahoo\" \"hasimoto.kotaro@gmail.com\" \"' + sbj + '\" \"' + body + '\"')
    except:
        pass


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
    global activity

    currentDateTime = datetime.now()
    day, tm = currentDateTime.strftime('%Y%m%d-%H%M%S').split('-')

    series[currentIndex][['date', 'time']] = [day, tm]
    series[currentIndex][['humid[%]', 'temp[*C]']] = [round(x, 2) if x else 0 for x in Adafruit_DHT.read_retry(DHT_SENSOR, DHT_PIN)]
    series[currentIndex][['CPU[*C]', 'CPU[v]', 'CPU[MHz]']] = [vcmd.measure_temp(), vcmd.measure_volts('core'), round(vcmd.measure_clock('arm') / 1000000)]
    series[currentIndex][['CPU[%]', 'memory[%]', 'rootfs[%]', 'usb[%]']] = [psutil.cpu_percent(interval = 1), psutil.virtual_memory().percent, psutil.disk_usage('/').percent, psutil.disk_usage('/home/pi/usb').percent]
    series[currentIndex]['activity'], oldestJPG, recentFiles = countMotion(previousDateTime, currentDateTime)
    
    if 80 < series[currentIndex]['usb[%]'] and oldestJPG:
        if os.path.exists(oldestJPG):
            os.remove(oldestJPG)
            if oldestJPG in recentFiles:
                del recentFiles[recentFiles.index(oldestJPG)]
        print(oldestJPG, 'deleted due to free space shortage.')

    '''
    if 95 < series[currentIndex]['usb[%]']:
        fname = min(glob(LOGDIR + '20*.csv'))
        os.remove(fname)
        print(fname, 'deleted due to free space shortage.')
    '''

    response = None
    activity += series[currentIndex]['activity']    
    if 0 < series[currentIndex]['activity']:

        msg = series[currentIndex]['time'][:2] + ':' + series[currentIndex]['time'][2:4] + ' '
        n = series[currentIndex]['activity']
        for li in range(len(lastMoveIndex)):
            lastMoveIndex[li] = (lastMoveIndex[li] + 1) % len(lastMoveIndex)
        lastMoves[lastMoveIndex[-1]] = (msg, str(n))
        
        if n < 10:
            msg += 'たろいもさんが起きました'
        elif n < 20:
            msg += 'たろいもさんがうろうろしてます'
        elif n < 30:
            msg += 'たろいもさんが走り回ってます'
        else:
            msg += 'たろいもさんが暴れてます'

        msg += ":" + str(n) + ' activity/分, '
        msg += '温度:' + str(series[currentIndex]['temp[*C]']) + '℃, '
        msg += '湿度:' + str(series[currentIndex]['humid[%]']) + '%'

        client = WebClient(token = os.environ["SLACK_API_TOKEN"])        
        try:
            response = client.chat_postMessage(
                channel = 'C018J2HN0UB',
                text = msg
            )

            for fname in getLastNImages(False, True, 5):
                if fname in recentFiles:
                    response = client.files_upload(
                        channels = 'C018J2HN0UB', 
                        file = fname,
                    ) 

        except urllib.error.URLError as e:
            print(response, '\n', e, '\n', currentDateTime)
            sendMail(msg, str(response) + str(e))
            pass            
        except:
            print(response, currentDateTime)
            sendMail(msg, str(response))
            pass
        
    if currentIndex % 10 == 0:

        drawChart(pd.DataFrame([y for y in \
                                [x for x in series if not pd.isnull(x['date'])]]))

        df = pd.DataFrame([y for y in \
                           [x for x in series if not pd.isnull(x['date'])] \
                           if y['date'] == day]) \
               .sort_values(by = ['date', 'time'], ascending = False).reset_index(drop = True)

        df.to_csv(LOGDIR + day + '.csv', encoding = 'utf-8', index = False)
        print(day + '.csv dumped with', len(df), 'records (' + tm[:2] + ':' + tm[2:4] + ':' + tm[4:] + ')')
        
        msg = currentDateTime.strftime('%H:%M') + ' 最近の10分間:' + str(activity) + ' activity, '
        msg += '温度:' + str(series[currentIndex]['temp[*C]']) + '℃, '
        msg += '湿度:' + str(series[currentIndex]['humid[%]']) + '%, '
        msg += 'CPU温度,使用率:' + str(series[currentIndex]['CPU[*C]']) + '℃,' + str(series[currentIndex]['CPU[%]']) + '%, '
        msg += 'メモリ使用率:' + str(series[currentIndex]['memory[%]']) + '%, '
        msg += 'SD,USB使用率:' + str(series[currentIndex]['rootfs[%]']) + '%, ' + str(series[currentIndex]['usb[%]']) + '%, '

        msg += '最近の動き:'
        for li in range(len(lastMoveIndex) - 1, -1, -1):
            if not lastMoveIndex[li] in lastMoves:
                break
            lm = lastMoves[lastMoveIndex[li]]
            msg += lm[0] + lm[1] + 'act, '
        
        activity = 0        
        client = WebClient(token = os.environ["SLACK_API_TOKEN"])
        try:
            response = client.chat_postMessage(
                channel = 'C018J2HN0UB',
                text = msg
            )
            for fname in getLastNImages(True, False, 0):
                response = client.files_upload(
                    channels = 'C018J2HN0UB', 
                    file = fname,
                )
            
        except urllib.error.URLError as e:
            print(response, '\n', e, currentDateTime)
            sendMail(msg, str(response) + str(e))
            pass            
        except:
            print(response, currentDateTime)
            sendMail(msg, str(response))
            pass
            

    '''
    if currentIndex % 10 == 0 or 0 < series[currentIndex]['activity']:
                
        sbj = ''
        for c in ['activity', 'temp[*C]', 'humid[%]', 'CPU[*C]', 'CPU[%]', 'memory[%]', 'rootfs[%]', 'usb[%]']:
            sbj += c + ':' + str(series[currentIndex][c]) + ', '

        body = ' '.join(df.columns.tolist())
        for i in range(10 if 10 < len(df.index) else len(df.index)):
            body += '\n'
            for c in df.columns[1:]:
                body += c + ':' + str(df.loc[i, c]) + ', '

        try:
            os.system('python3 mail.py \"yahoo\" \"hasimoto.kotaro@gmail.com\" \"' + sbj + '\" \"' + body + '\"')
        except:
            pass
    '''

    if tm.startswith('235'):
        df = pd.DataFrame([y for y in \
                           [x for x in series if not pd.isnull(x['date'])] \
                           if y['date'] == day]) \
               .sort_values(by = ['date', 'time'], ascending = False).reset_index(drop = True)

        df.to_csv(LOGDIR + day + '.csv', encoding = 'utf-8', index = False)
        print(day + '.csv dumped with', len(df), 'records (' + tm[:2] + ':' + tm[2:4] + ':' + tm[4:] + ')')    
        
    currentIndex = (currentIndex + 1) % len(series)
    previousDateTime = currentDateTime

    
if __name__ == '__main__':

    day = datetime.now().strftime('%Y%m%d')
    if os.path.exists(LOGDIR + day + '.csv'):
        
        df = pd.read_csv(LOGDIR + day + '.csv', encoding = 'utf-8', dtype = object).sort_values(by = ['date', 'time']).reset_index(drop = True)
        for i, v in df.iterrows():
            series[i][col] = v[col].tolist()
        currentIndex = len(df.index) % len(series)

        '''
        df = pd.DataFrame([y for y in \
                           [x for x in series if not pd.isnull(x['date'])] \
                           if y['date'] == day]) \
               .sort_values(by = ['date', 'time'], ascending = False).reset_index(drop = True)

        df.to_csv(day + '.csv', encoding = 'utf-8', index = False)
        exit(1)
        '''
        
    signal.signal(signal.SIGALRM, watch)
    signal.setitimer(signal.ITIMER_REAL, INTERVAL, INTERVAL)

    sendMail('TaroLogger started', str(currentIndex))
    
    while True:
        time.sleep(86400)

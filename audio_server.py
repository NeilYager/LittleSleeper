import pyaudio
import numpy as np
import time
import multiprocessing as mp
from multiprocessing.connection import Listener
import ctypes
from scipy import ndimage
from datetime import datetime, timedelta

THRESHOLD = 500
CHUNK_SIZE = 1024
FORMAT = pyaudio.paInt16
RATE = 44100
BUFFER_HOURS = 12
SAMPLE_TIME = 0.9  # how many seconds of audio to grab at a time
LISTENER_ADDRESS = ('localhost', 6000)

# TODO: test overflow (set to capture 10 mins)

def process_audio(shared_audio, shared_time, shared_pos, lock):
    """
    Endless loop: Grab some audio from the mic and record the maximum

    :param shared_audio:
    :param shared_time:
    :param shared_pos:
    :param lock:
    :return:
    """
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=1, rate=RATE,
                    input=True, output=True, frames_per_buffer=CHUNK_SIZE)

    while True:
        # grab audio
        audio = np.fromstring(stream.read(int(SAMPLE_TIME*RATE)), np.int16)
        current_time = time.time()

        # acquire lock
        lock.acquire()

        # record current time
        shared_time[shared_pos.value] = current_time

        # find the maximum volume in this time slice
        shared_audio[shared_pos.value] = np.abs(audio).max()

        # increment counter
        shared_pos.value = (shared_pos.value + 1) % len(shared_time)

        # release lock
        lock.release()

    # I've included the following code for completion, but unless the above
    #  loop is modified to include an interrupt it will never be executed
    stream.stop_stream()
    stream.close()
    p.terminate()


def format_time_difference(time1, time2):
    time_diff = datetime.fromtimestamp(time2) - datetime.fromtimestamp(time1)

    return str(time_diff).split('.')[0]


def process_requests(shared_audio, shared_time, shared_pos, lock):
    """
    Handle requests from the web server. First get the latest data, and
    then analyse it to find the current state of the baby.

    :param shared_audio:
    :param shared_time:
    :param shared_pos:
    :param lock:
    :return:
    """
    listener = Listener(LISTENER_ADDRESS)
    while True:
        conn = listener.accept()

        # get some parameters from the client
        parameters = conn.recv()

        # acquire lock
        lock.acquire()

        # convert to numpy arrays and get a copy of the data
        time_stamps = np.frombuffer(shared_time, np.float64).copy()
        audio_signal = np.frombuffer(shared_audio, np.int16).astype(np.float32)
        current_pos = shared_pos.value

        # release lock
        lock.release()

        # roll the arrays so that the latest readings are at the end
        buffer_len = time_stamps.shape[0]
        time_stamps = np.roll(time_stamps, shift=buffer_len-current_pos)
        audio_signal = np.roll(audio_signal, shift=buffer_len-current_pos)

        # normalise and apply some smoothing
        audio_signal /= parameters['upper_limit']
        audio_signal = ndimage.gaussian_filter1d(audio_signal, sigma=3, mode="reflect")

        # save the last hour for the plot
        audio_plot = audio_signal[-3600:]

        # ignore positions with no readings
        mask = time_stamps > 0
        time_stamps = time_stamps[mask]
        audio_signal = audio_signal[mask]

        # partition the audio history into blocks of type:
        #   1. crying, where the volume is greater than noise_threshold
        #   2. silence, where the volume is less than noise_threshold
        crying = audio_signal > parameters['noise_threshold']
        silent = audio_signal < parameters['noise_threshold']

        # join "crying blocks" that are closer together than min_quiet_time
        crying_blocks = []
        if np.any(crying):
            silent_labels, _ = ndimage.label(silent)
            silent_ranges = ndimage.find_objects(silent_labels)
            for silent_block in silent_ranges:
                start = silent_block[0].start
                stop = silent_block[0].stop

                # don't join silence blocks at the beginning or end
                if start == 0:# or stop == len(audio_signal):
                    continue

                interval_length = time_stamps[stop-1] - time_stamps[start]
                if interval_length < parameters['min_quiet_time']:
                    crying[start:stop] = True

            # find crying blocks start times and duration
            crying_labels, num_crying_blocks = ndimage.label(crying)
            crying_ranges = ndimage.find_objects(crying_labels)
            for cry in crying_ranges:
                start = time_stamps[cry[0].start]
                stop = time_stamps[cry[0].stop-1]
                duration = stop - start

                # ignore isolated noises (i.e. with a duration less than min_noise_time)
                if duration < parameters['min_noise_time']:
                    continue

                # save some info about the crying block
                crying_blocks.append({'start': start,
                                      'start_str': datetime.fromtimestamp(start).strftime("%I:%M:%S %p").lstrip('0'),
                                      'stop': stop,
                                      'duration': format_time_difference(start, stop)})

        # determine how long have we been in the current state
        time_current = time.time()
        time_crying = ""
        time_quiet = ""
        str_crying = "Baby noise for "
        str_quiet = "Baby quiet for "
        if len(crying_blocks) == 0:
            time_quiet = str_quiet + format_time_difference(time_stamps[0], time_current)
        else:
            if time_current - crying_blocks[-1]['stop'] < parameters['min_quiet_time']:
                time_crying = str_crying + format_time_difference(crying_blocks[-1]['start'], time_current)
            else:
                time_quiet = str_quiet + format_time_difference(crying_blocks[-1]['stop'], time_current)

        results = {'audio_plot': audio_plot,
                   'crying_blocks': crying_blocks,
                   'time_crying': time_crying,
                   'time_quiet': time_quiet}

        conn.send(results)

        conn.close()


def server():
    # create a buffer large enough to contain BUFFER_HOURS of audio
    buffer_len = int(BUFFER_HOURS * 60 * 60 * (1.0 / SAMPLE_TIME))

    # create shared memory
    lock = mp.Lock()
    shared_audio = mp.Array(ctypes.c_short, buffer_len, lock=False)
    shared_time = mp.Array(ctypes.c_double, buffer_len, lock=False)
    shared_pos = mp.Value('i', 0, lock=False)

    # start 2 processes:
    # 1. a process to continuously monitor the audio feed
    # 2. a process to handle requests for the latest data
    p1 = mp.Process(target=process_audio, args=(shared_audio, shared_time, shared_pos, lock))
    p2 = mp.Process(target=process_requests, args=(shared_audio, shared_time, shared_pos, lock))
    p1.start()
    p2.start()


if __name__ == '__main__':
    server()

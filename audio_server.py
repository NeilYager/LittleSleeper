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
#FORMAT = pyaudio.paInt16
RATE = 44100
BUFFER_HOURS = 12
SAMPLE_TIME = 0.9  # how many seconds of audio to grab at a time
LISTENER_ADDRESS = ('localhost', 6000)

if __name__ == '__main__':
    print pyaudio.__version__
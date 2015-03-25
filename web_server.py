import os
from datetime import datetime

import tornado.httpserver
import tornado.ioloop
import tornado.web
import tornado.websocket
import tornado.gen

from multiprocessing.connection import Client

AUDIO_ADDRESS = ('localhost', 6000)
HTTP_PORT = 8090

# The highest (practical) volume for the microphone, which is used to normalize the signal
#  This depends on: microphone sensitivity, distance to crib, amount of smoothing
UPPER_LIMIT = 25000

# After the signal has been normalized to the tange [0, 1], volumes higher than this will be
#  classified as noise.
# Vary based on: background noise, how loud the baby is, etc.
NOISE_THRESHOLD = 0.25

# number of seconds of quiet before transition mode from "noise" to "quiet"
MIN_QUIET_TIME = 30

# number of seconds of noise before transition mode from "quiet" to "noise"
MIN_NOISE_TIME = 5

clients = []


class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        self.render('index.html')


class WebSocketHandler(tornado.websocket.WebSocketHandler):
    def open(self):
        print "New connection"
        clients.append(self)

    def on_close(self):
        print "Connection closed"
        clients.remove(self)
 

def main():
    settings = {
        "static_path": os.path.join(os.path.dirname(__file__), "static"),
    }
    app = tornado.web.Application(
        handlers=[
            (r"/", IndexHandler),
            (r"/ws", WebSocketHandler),
        ], **settings
    )
    http_server = tornado.httpserver.HTTPServer(app)
    http_server.listen(HTTP_PORT)
    print "Listening on port:", HTTP_PORT

    def get_mic_data():
        # get the latest data from the audio server
        parameters = {"upper_limit": UPPER_LIMIT,
                      "noise_threshold": NOISE_THRESHOLD,
                      "min_quiet_time": MIN_QUIET_TIME,
                      "min_noise_time": MIN_NOISE_TIME}
        conn = Client(AUDIO_ADDRESS)
        conn.send(parameters)
        results = conn.recv()
        conn.close()
        now = datetime.now()
        results['date_current'] = '{dt:%A} {dt:%B} {dt.day}, {dt.year}'.format(dt=now)
        results['time_current'] = now.strftime("%I:%M:%S %p").lstrip('0')
        results['audio_plot'] = results['audio_plot'].tolist()
        for c in clients:
            c.write_message(results)
 
    main_loop = tornado.ioloop.IOLoop.instance()
    scheduler = tornado.ioloop.PeriodicCallback(get_mic_data, 1000, io_loop=main_loop)
    scheduler.start()
    main_loop.start()
 
if __name__ == "__main__":
    main()
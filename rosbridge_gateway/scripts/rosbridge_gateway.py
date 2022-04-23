#!/usr/bin/env python3
# Software License Agreement (BSD License)
#
# Copyright (c) 2012, Willow Garage, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of Willow Garage, Inc. nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.


import sys
import time

import rclpy
import roslibpy
from rclpy.node import Node
from tornado.ioloop import IOLoop, PeriodicCallback


def start_hook():
    IOLoop.instance().start()


def shutdown_hook():
    IOLoop.instance().stop()


class RosbridgeGatewayNode(Node):
    def __init__(self):
        super().__init__("rosbridge_gateway")

        ##################################################
        # Parameter handling                             #
        ##################################################

        # get tornado application parameters
        tornado_settings = {}
        tornado_settings["websocket_ping_interval"] = float(
            self.declare_parameter("websocket_ping_interval", 0).value
        )
        tornado_settings["websocket_ping_timeout"] = float(
            self.declare_parameter("websocket_ping_timeout", 30).value
        )
        if "--websocket_ping_interval" in sys.argv:
            idx = sys.argv.index("--websocket_ping_interval") + 1
            if idx < len(sys.argv):
                tornado_settings["websocket_ping_interval"] = float(sys.argv[idx])
            else:
                print("--websocket_ping_interval argument provided without a value.")
                sys.exit(-1)

        if "--websocket_ping_timeout" in sys.argv:
            idx = sys.argv.index("--websocket_ping_timeout") + 1
            if idx < len(sys.argv):
                tornado_settings["websocket_ping_timeout"] = float(sys.argv[idx])
            else:
                print("--websocket_ping_timeout argument provided without a value.")
                sys.exit(-1)

        remote_port = self.declare_parameter("remote_port", 9090).value
        if "--remote_port" in sys.argv:
            idx = sys.argv.index("--remote_port") + 1
            if idx < len(sys.argv):
                remote_port = int(sys.argv[idx])
            else:
                print("--remote_port argument provided without a value.")
                sys.exit(-1)
        remote_address = self.declare_parameter("remote_address", "localhost").value
        if "--remote_address" in sys.argv:
            idx = sys.argv.index("--remote_address") + 1
            if idx < len(sys.argv):
                remote_address = int(sys.argv[idx])
            else:
                print("--remote_address argument provided without a value.")
                sys.exit(-1)

        local_port = self.declare_parameter("local_port", 9091).value
        if "--local_port" in sys.argv:
            idx = sys.argv.index("--local_port") + 1
            if idx < len(sys.argv):
                local_port = int(sys.argv[idx])
            else:
                print("--local_port argument provided without a value.")
                sys.exit(-1)
        local_address = self.declare_parameter("local_address", "localhost").value
        if "--local_address" in sys.argv:
            idx = sys.argv.index("--local_address") + 1
            if idx < len(sys.argv):
                local_address = int(sys.argv[idx])
            else:
                print("--local_address argument provided without a value.")
                sys.exit(-1)

        retry_startup_delay = self.declare_parameter("retry_startup_delay", 2.0).value  # seconds.
        if "--retry_startup_delay" in sys.argv:
            idx = sys.argv.index("--retry_startup_delay") + 1
            if idx < len(sys.argv):
                retry_startup_delay = int(sys.argv[idx])
            else:
                print("--retry_startup_delay argument provided without a value.")
                sys.exit(-1)

        ##################################################
        # Done with parameter handling                   #
        ##################################################

        connected = False
        while not connected and self.context.ok():
            try:
                self.local = roslibpy.Ros(host=local_address, port=local_port)
                self.remote = roslibpy.Ros(host=remote_address, port=remote_port)
                self.local.run()
                self.remote.run()
            except OSError as e:
                self.get_logger().warn(
                    "Unable to start Gateway: {} " "Retrying in {}s.".format(e, retry_startup_delay)
                )
                time.sleep(retry_startup_delay)
            else:
                self.get_logger().info(
                    f"Rosbridge Gateway is connected to remote server {remote_address}:{remote_port} and to local server {local_address}:{local_port}"
                )
                connected = True

        self.deny_topics = [
            "/client_count",
            "/connected_clients",
            "/parameter_events",
            "/rosout",
        ]
        self.advertised_topics = []
        self.local_topics = []
        self.remote_topics = []

        self.create_timer(1, self.update_topic_list)
        self.create_timer(1, self.advertise_to_remote)
        self.create_timer(1, self.advertise_to_local)
        self.create_timer(1, self.test)

    def update_topic_list(self):
        local_list = list(
            set(roslibpy.Ros.get_topics(self.local, callback=None))
            - set(self.advertised_topics)
            - set(self.deny_topics)
        )
        for topic in local_list:
            if not any(x.name == topic for x in self.local_topics):
                self.get_logger().info(f"add local topic {topic} to list")
                self.local_topics.append(
                    roslibpy.Topic(
                        self.local, topic, roslibpy.Ros.get_topic_type(self.local, topic)
                    )
                )
        remote_list = list(
            set(roslibpy.Ros.get_topics(self.remote, callback=None))
            - set(self.advertised_topics)
            - set(self.deny_topics)
        )
        for topic in remote_list:
            if not any(x.name == topic for x in self.remote_topics):
                self.get_logger().info(f"add remote topic {topic} to list")
                self.remote_topics.append(
                    roslibpy.Topic(
                        self.remote, topic, roslibpy.Ros.get_topic_type(self.remote, topic)
                    )
                )

    def test(self):
        for topic in self.local_topics:
            if topic.is_subscribed:
                self.get_logger().info(f"topic {topic.name} is subscribed")

    def advertise_to_remote(self):
        for topic in self.local_topics:
            if not topic.is_subscribed:
                self.get_logger().info(f"advertise {topic.name} to remote")
                self.advertised_topics.append(topic.name)
                remote = roslibpy.Topic(self.remote, topic.name, topic.message_type)
                remote.advertise()
                topic.subscribe(lambda msg: remote.publish(msg))

    def advertise_to_local(self):
        for topic in self.remote_topics:
            if not topic.is_subscribed:
                self.get_logger().info(f"advertise {topic.name} to local")
                self.advertised_topics.append(topic.name)
                local = roslibpy.Topic(self.local, topic.name, topic.message_type)
                local.advertise()
                topic.subscribe(lambda msg: local.publish(msg))


def main(args=None):
    if args is None:
        args = sys.argv

    rclpy.init(args=args)
    node = RosbridgeGatewayNode()

    spin_callback = PeriodicCallback(lambda: rclpy.spin_once(node, timeout_sec=0.01), 1000)
    spin_callback.start()
    try:
        start_hook()
    except KeyboardInterrupt:
        node.get_logger().info("Exiting due to SIGINT")

    node.destroy_node()
    rclpy.shutdown()
    shutdown_hook()  # shutdown hook to stop the server


if __name__ == "__main__":
    main()

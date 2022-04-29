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


import json
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

        self.servers = []

        self.servers.append(roslibpy.Ros(host=local_address, port=local_port))
        self.servers.append(roslibpy.Ros(host=remote_address, port=remote_port))
        self.servers[0].server_id = "local"
        self.servers[1].server_id = "remote"

        connected = False
        while not connected and self.context.ok():
            try:
                for server in self.servers:
                    server.run()
                    if server.is_connected:
                        self.get_logger().info(f"Gateway is connected to server {server}")
                        connected = True
                    else:
                        connected = False
            except OSError as e:
                self.get_logger().warn(
                    "Unable to start Gateway: {} " "Retrying in {}s.".format(e, retry_startup_delay)
                )
                time.sleep(retry_startup_delay)
            else:
                self.get_logger().info(f"Gateway is connected to all servers")

        self.deny_topics = [
            "/client_count",
            "/connected_clients",
            "/parameter_events",
            "/rosout",
        ]
        self.deny_hosts = [
            "/rosapi",
            "/rosapi_params",
            "/rosbridge_websocket",
            "/rosbridge_gateway",
        ]

        self.topics = []

        # String list
        self.advertised_topics = []
        self.local_subscriber = []
        self.remote_subscriber = []
        self.local_publisher = []
        self.remote_publisher = []
        # Object list
        self.local_topics = []
        self.remote_topics = []

        self.create_timer(0.1, self.add_topics_to_list)
        self.create_timer(0.1, self.remove_topics_from_list)

    def add_topics_to_list(self):
        self.get_logger().info(f"add list...  {len(self.topics)}")
        for server in self.servers:
            # self.get_logger().info(f"update server topics {server.server_id}")
            topics = list(
                set(roslibpy.Ros.get_topics(server, callback=None)) - set(self.deny_topics)
            )
            for topic in topics:
                if not any(element.name == topic for element in self.topics):
                    self.get_logger().info(f"add {server.server_id} topic {topic} to list")
                    _topic = roslibpy.Topic(
                        server, topic, roslibpy.Ros.get_topic_type(server, topic)
                    )
                    _topic.peers = {}
                    self.topics.append(_topic)

    def remove_topics_from_list(self):
        self.get_logger().info(f"remove list...  {len(self.topics)}")
        for server in self.servers:
            for topic in self.topics:
                if topic.ros is server and topic.name not in topics:
                    for server in topic.peers:
                        self.get_logger().info(
                            f"unadvertise topic {topic.name} from server {server.server_id}"
                        )
                        topic.peers[server].unadvertise()
                    self.get_logger().info(
                        f"remove topic {topic.name} from server {server.server_id}"
                    )
                    self.topics.remove(topic)


#
#        for topic in self.topics:
#            for server in self.servers:
#                if topic.ros is not server:
#                    if server not in topic.peers:
#                        self.get_logger().info(
#                            f"add peer server {server.server_id} to {topic.name}"
#                        )
#                        topic.peers[server] = roslibpy.Topic(server, topic.name, topic.message_type)
#                    if not topic.peers[server].is_advertised:
#                        self.get_logger().info(f"advertise {topic.name} to {server.server_id}")
#                        topic.peers[server].advertise()


#            if not hasattr(topic, "peer"):
#                topic.peer = roslibpy.Topic(self.remote, topic.name, topic.message_type)
#            if not topic.peer.is_advertised and topic.name in self.local_publisher:
#                self.get_logger().info(f"advertise {topic.name} to remote")
#                self.advertised_topics.append(topic.name)
#                topic.peer.advertise()
#            if not topic.is_subscribed and topic.name in self.remote_subscriber:
#                self.get_logger().info(f"topic {topic.name} is subscribed")
#                topic.subscribe(lambda msg: topic.peer.publish(msg))
#            if topic.is_subscribed and topic.name not in self.remote_subscriber:
#                self.get_logger().info(f"unsubscribe topic {topic.name} to remote")
#                topic.unsubscribe()
#            if topic.peer.is_advertised and topic.name not in self.local_publisher:
#                self.get_logger().info(f"unadvertise topic {topic.name} to remote")
#                topic.peer.unadvertise()
#                self.advertised_topics.remove(topic.name)
#                self.get_logger().info(f"remove topic {topic.name} from local topic list")
#                self.local_topics.remove(topic)


def main(args=None):
    if args is None:
        args = sys.argv

    rclpy.init(args=args)
    node = RosbridgeGatewayNode()

    spin_callback = PeriodicCallback(lambda: rclpy.spin_once(node, timeout_sec=0.01), 1)
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

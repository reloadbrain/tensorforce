# Copyright 2017 reinforce.io. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""
Models provide the general interface to TensorFlow functionality,
manages TensorFlow session and execution. In particular, a agent for reinforcement learning
always needs to provide a function that gives an action, and one to trigger updates.
A agent may use one more multiple neural networks and implement the update logic of a particular
RL algorithm.

"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

import logging
import tensorflow as tf

from tensorforce import TensorForceError, util
from tensorforce.core.optimizers import optimizers


log_levels = {
    'info': logging.INFO,
    'debug': logging.DEBUG,
    'critical': logging.CRITICAL,
    'warning': logging.WARNING,
    'fatal': logging.FATAL
}


class Model(object):

    allows_discrete_actions = None
    allows_continuous_actions = None

    default_config = dict(
        discount=0.97,
        exploration=None,
        exploration_args=None,
        exploration_kwargs=None,
        learning_rate=0.0001,
        optimizer='adam',
        optimizer_args=None,
        optimizer_kwargs=None,
        device=None,
        tf_saver=False,
        tf_summary=None,
        log_level='info'
    )

    def __init__(self, config):
        """
        Creates a base reinforcement learning model with the specified configuration.
        
        Args:
            config: 
        """

        assert self.__class__.allows_discrete_actions is not None and self.__class__.allows_continuous_actions is not None
        config.default(Model.default_config)

        # TODO: change/remove
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(log_levels[config.log_level])

        self.discount = config.discount

        # TODO: TF, initialization, loss, optimization (better!)
        tf.reset_default_graph()
        self.session = tf.Session()

        with tf.device(config.device):
            self.create_tf_operations(config)
            if self.optimizer:
                self.loss = tf.losses.get_total_loss()
                self.optimize = self.optimizer.minimize(self.loss)

        if config.tf_saver:
            self.saver = tf.train.Saver()
        else:
            self.saver = None
        if config.tf_summary is not None:
            self.writer = tf.summary.FileWriter(config.tf_summary, graph=tf.get_default_graph())
        else:
            self.writer = None
        self.session.run(tf.global_variables_initializer())

    def create_tf_operations(self, config):
        """
        Creates generic TensorFlow operations and placeholders required for models.
        
        Args:
            config: Model configuration which must contain entries for states and actions.

        Returns:

        """
        self.action_taken = dict()
        self.internal_inputs = list()
        self.internal_outputs = list()
        self.internal_inits = list()

        # Placeholders
        with tf.variable_scope('placeholder'):

            # States
            self.state = dict()
            for name, state in config.states:
                self.state[name] = tf.placeholder(dtype=util.tf_dtype(state.type), shape=(None,) + tuple(state.shape), name=name)

            # Actions
            self.action = dict()
            self.discrete_actions = []
            self.continuous_actions = []

            for name, action in config.actions:
                if action.continuous:
                    if not self.__class__.allows_continuous_actions:
                        raise TensorForceError()
                    self.action[name] = tf.placeholder(dtype=util.tf_dtype('float'), shape=(None,), name=name)
                else:
                    if not self.__class__.allows_discrete_actions:
                        raise TensorForceError()
                    self.action[name] = tf.placeholder(dtype=util.tf_dtype('int'), shape=(None,), name=name)

            self.reward = tf.placeholder(dtype=tf.float32, shape=(None,), name='reward')
            self.terminal = tf.placeholder(dtype=tf.bool, shape=(None,), name='terminal')

        # Optimizer
        if config.optimizer is not None:
            learning_rate = config.learning_rate
            with tf.variable_scope('optimization'):
                optimizer = util.function(config.optimizer, optimizers)
                args = config.optimizer_args or ()
                kwargs = config.optimizer_kwargs or {}
                self.optimizer = optimizer(learning_rate, *args, **kwargs)
        else:
            self.optimizer = None

    def reset(self):
        return list(self.internal_inits)

    def get_action(self, state, internals):
        fetches = {action: action_taken for action, action_taken in self.action_taken.items()}
        fetches.update({n: internal for n, internal in enumerate(self.internal_outputs)})

        feed_dict = {state_input: (state[name],) for name, state_input in self.state.items()}
        feed_dict.update({internal: (internals[n],) for n, internal in enumerate(self.internal_inputs)})

        fetched = self.session.run(fetches=fetches, feed_dict=feed_dict)

        action = {name: fetched[name][0] for name in self.action}
        internals = [fetched[n][0] for n in range(len(self.internal_outputs))]
        return action, internals

    def update(self, batch):
        fetches = [self.optimize, self.loss]

        feed_dict = {state: batch['states'][name] for name, state in self.state.items()}
        feed_dict.update({action: batch['actions'][name] for name, action in self.action.items()})
        feed_dict[self.reward] = batch['rewards']
        feed_dict[self.terminal] = batch['terminals']
        feed_dict.update({internal: batch['internals'][n] for n, internal in enumerate(self.internal_inputs)})

        _, loss = self.session.run(fetches=fetches, feed_dict=feed_dict)

        # if self.logger:
        #     self.logger.debug('loss = ' + str(loss))

    def load_model(self, path):
        self.saver.restore(self.session, path)

    def save_model(self, path):
        self.saver.save(self.session, path)

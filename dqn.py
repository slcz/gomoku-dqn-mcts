
################################################################################
#
# Q learning
#
################################################################################

from agent import (Agent, RandomAgent)
from rules import (Rules)
import tensorflow as tf
import numpy as np
import os
from collections import deque
import random
from SumTree import SumTree
import math

FLAGS = tf.app.flags.FLAGS
tf.app.flags.DEFINE_boolean('display_AI', False, """Display AI thinking""")
tf.app.flags.DEFINE_string('summaries_dir', '/tmp/summaries', """summary dir""")
tf.app.flags.DEFINE_string('model_dir', './saved_models',
        """Directory to save the trained models""")
tf.app.flags.DEFINE_string('agent1_model', None, """agent1 model""")
tf.app.flags.DEFINE_string('agent2_model', None, """agent2 model""")
tf.app.flags.DEFINE_boolean('agent1_auto', False, """agent1 auto resolve""")
tf.app.flags.DEFINE_boolean('agent2_auto', False, """agent2 auto resolve""")
tf.app.flags.DEFINE_float('learn_rate', 0.0002, """learning rate""")
tf.app.flags.DEFINE_string('copy_from', None, """copy from model""")
tf.app.flags.DEFINE_string('copy_to', None, """copy to model""")
tf.app.flags.DEFINE_float('train_epsilon', 0.2, """epsilon greedy""")
tf.app.flags.DEFINE_float('test_epsilon', 0.02, """epsilon greedy""")
tf.app.flags.DEFINE_float('mcts_epsilon', 0.2, """epsilon greedy""")
tf.app.flags.DEFINE_float('epsilon_decay', 0.95, """epsilon decay rate""")
tf.app.flags.DEFINE_float('priority_weight', 1.0, """priority wieght 0-1""")
tf.app.flags.DEFINE_integer('trainbatch', 64, """training batch size""")
tf.app.flags.DEFINE_integer('replay_size', 1000000, """replay buffer size""")
tf.app.flags.DEFINE_integer('train_iterations', 1, """training iterations""")
tf.app.flags.DEFINE_integer('train_interval',   1, """training interval""")
tf.app.flags.DEFINE_integer('observations', 10000, """initial observations""")
tf.app.flags.DEFINE_integer('save_interval', 5000, """intervals to save model""")
tf.app.flags.DEFINE_integer('decay_interval', 5000, """intervals to epsilon decay""")
tf.app.flags.DEFINE_float('gamma', 0.9, """gamma""")
tf.app.flags.DEFINE_integer('copy_network_interval', 10000, """intervals to copy network from qnet to targetnet""")
tf.app.flags.DEFINE_integer('montecarlo_parallelism', 256, """Monte Carlo execution agents""")
tf.app.flags.DEFINE_integer('montecarlo_totalsteps', 4096, """Monte Carlo time limitation""")
tf.app.flags.DEFINE_integer('montecarlo_minsteps', 1024, """Monte Carlo time limitation""")
tf.app.flags.DEFINE_float('uct_exploration', 0.2, """UCT exploration parameter""")

class Network:
    def __init__(self, size, scope, session, readonly = True):
        self.size = size
        self.scope = scope
        self.readonly = readonly
        tf.contrib.framework.get_or_create_global_step()
        with tf.variable_scope(scope):
            self.init_network()
        self.session = session
        self.saver = tf.train.Saver(self.savable_variables())
        if not os.path.exists(FLAGS.model_dir):
            os.makedirs(FLAGS.model_dir)
        self.path = os.path.join(FLAGS.model_dir, self.scope)
        if not os.path.exists(self.path):
            os.makedirs(self.path)
        self.model_location = os.path.join(self.path, "model")

    def savable_variables(self):
        vs = tf.get_collection(tf.GraphKeys.MODEL_VARIABLES, scope=self.scope)
        if not self.readonly:
            vs.append(tf.contrib.framework.get_global_step())
        return vs

    def save(self):
        assert(self.saver)
        steps = self.session.run(tf.contrib.framework.get_global_step())
        checkpoint = tf.train.latest_checkpoint(self.path)
        self.saver.save(self.session, self.model_location, steps)
        print("SAVING PARAMETERS STEP = {}".format(steps))

    def restore(self):
        assert(self.saver)
        latest_checkpoint = tf.train.latest_checkpoint(self.path)
        if latest_checkpoint:
            self.saver.restore(self.session, latest_checkpoint)
            steps = self.session.run(tf.contrib.framework.get_global_step())
            print("RESTORE PARAMETERS {} STEP = {}".format(latest_checkpoint, steps))

    def init_network(self):
        flatsize = self.size ** 2
        self.input = tf.placeholder(dtype = tf.float32,
                shape = [None, self.size, self.size, 3],
                name = "input")
        self.y = tf.placeholder(shape = [None], dtype = tf.float32, name = "y")
        self.actions = tf.placeholder(shape=[None, 2], dtype=tf.int32,
                name = "actions")
        self.actions_flat = tf.reshape( \
                tf.slice(self.actions, [0, 0], [-1, 1]) \
                * self.size + tf.slice(self.actions, [0, 1], [-1, 1]), [-1])

        net = tf.contrib.layers.conv2d(self.input, 64, 5, 1,
                activation_fn=tf.nn.relu, padding='SAME', scope='conv1')
        net = tf.contrib.layers.conv2d(net, 64, 3, 1,
                activation_fn=tf.nn.relu, padding='SAME', scope='conv2')
        net = tf.contrib.layers.conv2d(net, 64, 3, 1,
                activation_fn=tf.nn.relu, padding='SAME', scope='conv3')
        net = tf.contrib.layers.conv2d(net, 64, 3, 1,
                activation_fn=tf.nn.relu, padding='SAME', scope='conv4')
        net = tf.contrib.layers.conv2d(net, 64, 3, 1,
                activation_fn=tf.nn.relu, padding='SAME', scope='conv5')
        net = tf.contrib.layers.conv2d(net, 64, 3, 1,
                activation_fn=tf.nn.relu, padding='SAME', scope='conv6')
        net = tf.contrib.layers.conv2d(net, 64, 3, 1,
                activation_fn=tf.nn.relu, padding='SAME', scope='conv7')
        net = tf.contrib.layers.conv2d(net, 64, 3, 1,
                activation_fn=tf.nn.relu, padding='SAME', scope='conv8')
        net = tf.contrib.layers.conv2d(net, 1, 1, 1,
                activation_fn=None, padding='SAME', scope='onebyone')
        self.predictions = tf.contrib.layers.flatten(net)
        samples = tf.shape(self.input)[0]
        masks = tf.reshape(tf.slice(self.input, [0, 0, 0, 2], [-1, -1, -1, 1]),
                [samples, -1])
        rev_masks = 1.0 - masks
        self.legal_moves = self.predictions * rev_masks  + \
                tf.transpose(tf.transpose(masks) *         \
                (tf.reduce_min(self.predictions, reduction_indices=[1]) - 1.0))

        # [0, output, 2*output, ..., (samples-1)*output] + actions
        self.index = tf.range(samples) * tf.shape(self.predictions)[1] + \
                self.actions_flat
        self.pred = tf.gather(tf.reshape(self.predictions, [-1]), self.index)
        self.losses = tf.squared_difference(self.y, self.pred)
        self.loss = tf.reduce_mean(self.losses)
        self.optimizer=tf.train.RMSPropOptimizer(FLAGS.learn_rate, 0.99)
        self.train = self.optimizer.minimize(self.loss,
                global_step=tf.contrib.framework.get_global_step())
        self.scores_input = tf.placeholder(dtype = tf.float32,
                            shape = [None], name = "scores_input")
        self.train_stage = tf.placeholder(dtype = tf.int32,
                            shape = [None], name = "train_stage")
    def create_summary(self):
        tf.summary.scalar('loss', self.loss)
        tf.summary.scalar('max loss', tf.reduce_max(self.losses))
        tf.summary.scalar('scores', tf.reduce_mean(self.scores_input))
        tf.summary.scalar('stage', tf.reduce_mean(tf.to_float(self.train_stage)))
        for s in tf.trainable_variables():
            if 'weights' in s.name and s.name.startswith(self.scope):
                tf.summary.histogram(s.name, s)
            if 'biases' in s.name and s.name.startswith(self.scope):
                tf.summary.histogram(s.name, s)

class CopyNetwork:
    def __init__(self, src, dst):
        w_src = [s for s in tf.trainable_variables()
                if s.name.startswith(src.scope)]
        w_dst = [s for s in tf.trainable_variables()
                if s.name.startswith(dst.scope)]
        self.copy_ops = []
        for s, d in zip(w_src, w_dst):
            self.copy_ops.append(d.assign(s))

    def copy(self, session):
        session.run(self.copy_ops)

class DqnAgent(Agent):
    state_self     = 0
    state_opponent = 1
    state_mask     = 2
    def __init__(self, size, session, scope, threads):
        super().__init__(size, session, scope, threads)
        self.autoresolve = False
        self.rules = Rules(size, FLAGS.connections)
        self.test_mode = False
        self.epsilon = 0.0
        self.board = None
    def clear(self):
        super().clear()
        self.buffered_move = None
        self.board = np.zeros((self.size, self.size), dtype = np.int32), \
                     np.zeros((self.size, self.size), dtype = np.int32), \
                     np.zeros((self.size, self.size), dtype = np.int32)
        self.fst_move = self.snd_move = None
    def update_state_(self, position, mover):
        mask = self.board[2]
        mover_board = self.board[mover]
        assert(mask[position] == 0.0 and mover_board[position] == 0.0)
        mask[position]  = 1.0
        mover_board[position] = 1.0
    @staticmethod
    def select(input, network):
        stacked = np.stack(input, axis = 0)
        pred, out = network.session.run([network.predictions,
                    network.legal_moves],
                    feed_dict = { network.input : stacked } )
        m = np.argmax(out, axis = 1)
        return m, out
    def self_move(self, _):
        fst, snd, mask = self.board
        move = None
        if self.autoresolve and self.fst_move and self.snd_move:
            if move == None:
                win_condition, set = self.rules.check_win(self.fst_move, fst, mask)
                if win_condition:
                    for s in set:
                        x, y = s // self.size, s % self.size
                        if fst[(x, y)] == 0.0:
                            move = x, y
                            break
            if move == None:
                win_condition, set = self.rules.check_win(self.snd_move, snd, mask)
                if win_condition:
                    for s in set:
                        x, y = s // self.size, s % self.size
                        move = x, y
                        if snd[(x, y)] == 0.0:
                            move = x, y
                            break
        m, q = self.buffered_move
        if move == None:
            if random.uniform(0, 1) < self.epsilon:
                x, y = move = super().random_policy(mask)
            else:
                assert(self.buffered_move != None)
                x, y = move = m // self.size, m % self.size
        self.buffered_move = None
        self.update_state_(move, DqnAgent.state_self)
        self.fst_move = move
        return move, q
    def opponent_move(self, position, _):
        self.update_state_(position, DqnAgent.state_opponent)
        self.snd_move = position

class Experience:
    def __init__(self, initial_board, self_mv, oppo_mv, new_board, reward, end, q, step):
        self.initial_board = initial_board
        self.self_move     = self_mv
        self.opponent_move = oppo_mv
        self.new_board     = new_board
        self.reward        = reward
        self.end           = end
        self.q             = q
        self.step          = step

class DqntrainAgentOne(DqnAgent):
    def __init__(self, size, session, scope, threads):
        super().__init__(size, session, scope, threads)
        self.q = 0.0
        self.experience_queue = []
        self.clear()
        self.epsilon = FLAGS.train_epsilon
    def clear(self):
        super().clear()
        self.opponent_mv = None
        self.self_mv = None
        self.orig_board = None
    def append_replay_buf(self, o, s_m, o_m, n, rew, end, q):
        state = Experience(o, s_m, o_m, n, rew, end, q, 0)
        self.experience_queue.append(state)
    def self_move(self, thread):
        a, b, c = self.board
        new_board = a.copy(), b.copy(), c.copy()
        if self.orig_board:
            self.append_replay_buf(self.orig_board, self.self_mv,
                    self.opponent_mv, new_board, 0.0, False, self.q)
        self.orig_board = new_board
        self.self_mv, self.q = super().self_move(thread)
        x, y = self.self_mv
        self.q = self.q[x * self.size + y]
        return self.self_mv
    def opponent_move(self, move, thread):
        super().opponent_move(move, thread)
        self.opponent_mv = move
    def finish(self, reward, thread):
        a, b, c = self.board
        new_board = a.copy(), b.copy(), c.copy()
        if self.orig_board:
            self.append_replay_buf(self.orig_board, self.self_mv,
                self.opponent_mv, new_board, reward, True, self.q)

def transform(new, ini, move, fun, funmove):
    a, b, c = new
    a = fun(a)
    b = fun(b)
    c = fun(c)
    d, e, f = ini
    d = fun(d)
    e = fun(e)
    f = fun(f)
    return (a, b, c), (d, e, f), funmove(move)

class DqntrainAgent(Agent):
    def __init__(self, size, session, scope, threads):
        super().__init__(size, session, scope, threads)
        self.replay = SumTree(FLAGS.replay_size)
        self.scores = deque()
        self.scores.append(0.0)
        self.nr_games = 0
        self.losses = []
        self.q_network = Network(self.size, self.scope + '/q', self.session)
        self.q_network.create_summary()
        self.train_writer = tf.summary.FileWriter(
                FLAGS.summaries_dir + '/train', session.graph)
        self.merged = tf.summary.merge_all()
        self.target_network = Network(self.size, self.scope + '/target',
                self.session)
        self.copy_network = CopyNetwork(self.q_network, self.target_network)
        self.children = []
        for _ in range(threads):
            self.children.append(DqntrainAgentOne(size, session, scope, 0))
        self.network_restored = False
    def set_autoresolve(self, resolve):
        for i in self.children:
            i.autoresolve = resolve
    def clear(self):
        super().clear()
        for child in self.children:
            child.clear()
        if self.network_restored == False:
            assert(self.q_network != None)
            self.q_network.restore()
            self.network_restored = True
    def name(self):
        return "a"
    def self_move(self, thread):
        agent = self.children[thread]
        if agent.buffered_move == None:
            inputs = []
            for i in self.children:
                inputs.append(np.stack(i.board, axis = -1))
            m, Q = DqnAgent.select(inputs, self.q_network)
            for a, move, q in zip(self.children, m, Q):
                assert(move != None)
                a.buffered_move = (move, q)
        assert(agent.buffered_move != None)
        return agent.self_move(thread)
    def opponent_move(self, move, thread):
        agent = self.children[thread]
        agent.opponent_move(move, thread)
    def train_step(self):
        total = self.replay.total()
        mini_batch = []
        for _ in range(FLAGS.trainbatch):
            s = random.uniform(0.0, total)
            mini_batch.append(self.replay.get(s))

        inputs  = []
        ends    = []
        orig    = []
        actions = []
        rewards = []
        stages  = []
        for idx, prio, sample in mini_batch:
            assert(sample.q == prio)
            self_move = sample.self_move
            new_board = sample.new_board
            initial_board = sample.initial_board
            # data augmentation
            if random.random() < 0.5:
                new_board, initial_board, self_move = \
                    transform(new_board, initial_board, self_move,
                              lambda x: np.transpose(x),
                              lambda x: (x[1], x[0]))
            if random.random() < 0.5:
                new_board, initial_board, self_move = \
                    transform(new_board, initial_board, self_move,
                              lambda x: np.flip(x, axis = 0),
                              lambda x: (self.size - 1 - x[0], x[1]))
            if random.random() < 0.5:
                new_board, initial_board, self_move = \
                    transform(new_board, initial_board, self_move,
                              lambda x: np.flip(x, axis = 1),
                              lambda x: (x[0], self.size - 1 - x[1]))
            a, b, c = new_board
            assert(a[self_move] == True and b[self_move] == False and c[self_move] == True)
            a, b, c = initial_board
            assert(a[self_move] == False and b[self_move] == False and c[self_move] == False)
            inputs.append(np.stack(new_board, axis = -1))
            ends.append(1 - sample.end)
            orig.append(np.stack(initial_board, axis = -1))
            actions.append(self_move)
            rewards.append(sample.reward)
            stages.append(sample.step)
        move, _ = DqnAgent.select(inputs, self.q_network)
        _, outtgt = DqnAgent.select(inputs, self.target_network)
        best = np.array(ends) * outtgt[range(len(move)), move]
        outtgt = rewards + best * FLAGS.gamma

        origmove, outorig = DqnAgent.select(orig, self.q_network)
        q = outorig[range(len(origmove)), origmove]
        newq = np.power(np.absolute(q - outtgt) + 0.00001, FLAGS.priority_weight)
        acc = 0.0
        for (i, (idx, _, data)) in enumerate(mini_batch):
            p = newq[i]
            data.q = p
            self.replay.update(idx, p)
            acc += p

        step_var = tf.contrib.framework.get_global_step()
        summary, _, loss, steps = self.q_network.session.run(
                [self.merged, self.q_network.train,
                    self.q_network.loss, step_var],
                feed_dict = { self.q_network.input : orig,
                              self.q_network.y : outtgt,
                              self.q_network.actions : actions,
                              self.q_network.scores_input : self.scores,
                              self.q_network.train_stage : stages})
        if steps > 0 and steps % 10 == 0:
            self.train_writer.add_summary(summary, steps)
        if steps > 0 and steps % FLAGS.save_interval == 0:
            self.q_network.save()
        if steps > 0 and steps % FLAGS.decay_interval == 0:
            for child in self.children:
                child.epsilon *= FLAGS.epsilon_decay
            print("New Epsilon {}".format(self.children[0].epsilon))
        self.losses.append(loss)

    def gameend(self):
        print("Saving latest parameters")
        self.q_network.save()

    def finish(self, reward, thread):
        self.scores.append(reward)
        if len(self.scores) > 1000:
            self.scores.popleft()

        agent = self.children[thread]
        agent.finish(reward, thread)
        queue = agent.experience_queue
        for i, elem in enumerate(queue):
            q = elem.q
            if elem.end:
                qn = elem.reward
            else:
                qn = queue[i + 1].q * FLAGS.gamma
            elem.q = pow(abs(q - qn) + 0.00001, FLAGS.priority_weight)
            elem.step = len(queue) - i
        while len(queue) > 0:
            elem = queue.pop()
            self.replay.add(elem.q, elem)
        if self.nr_games > FLAGS.observations and \
           self.nr_games % FLAGS.train_interval == 0:
            for _ in range(FLAGS.train_iterations):
                self.train_step()
        if self.nr_games % FLAGS.copy_network_interval == 0:
            self.copy_network.copy(self.session)
            print("copy to target network")
        self.nr_games += 1

    def info(self):
        if not self.losses:
            return
        print(" loss = {:.3f} ".format(sum(self.losses) / len(self.losses)), end="")
        self.losses = []

class MonteCarloTree:
    def __init__(self, size):
        self.size = size
        self.slots = size ** 2
        self.prior = None
        self.children = []
        for _ in range(self.slots):
            self.children.append(None)
        self.total  = 0.0
        self.reward = 0.0
    #
    # using UCT formula, evaluation each possible next move.
    # returns the position of the best valuation.
    #
    def select(self, mask):
        evaluations = np.zeros(self.slots)
        for i in range(self.slots):
            if mask[i]:
                value = 0.0
            elif self.children[i] == None or self.children[i].total == 0.0:
                value = float("inf")
            else:
                c = self.children[i]
                v1 = c.reward / c.total
                v2 = FLAGS.uct_exploration * math.sqrt(math.log(self.total) / c.total)
                v3 = self.prior[i] / c.total
                value = v1 + v2 + v3
            evaluations[i] = value
        seq = np.random.permutation(self.slots)
        e = evaluations[seq]
        pos = seq[np.argmax(e)]
        assert(np.amax(evaluations) == evaluations[pos])
        return pos

class MonteCarloExploer:
    state_init            = 0
    state_select          = 1
    state_simulation      = 2
    state_backpropagation = 3
    state_waitfor_move    = 4
    def __init__(self, size, board, tree, network):
        self.network = network
        self.size  = size
        self.tree  = tree
        self.orig  = board
        self.rules = Rules(size, FLAGS.connections)
        self.nr_moves = 0
        self.reinitialize()

    def reinitialize(self):
        self.tree.total += 1.0
        self.nr_moves = 0
        a, b = self.orig
        self.board = a.copy(), b.copy(), a + b
        self.state = MonteCarloExploer.state_select
        self.trace = [self.tree]
        self.termination = False
        self.reward = 0.0
        self.pending_state = None
        self.move  = None
        self.node = self.tree

    def step(self):
        return_value = 0
        if self.state == MonteCarloExploer.state_select:
            fst, snd, m = self.board
            if self.node.prior is None:
                state = np.stack(self.board, axis = -1)
                moves, Q = DqnAgent.select(np.expand_dims(state, axis = 0), self.network)
                Q = Q.reshape(-1)
                Q = Q - Q.min()
                Q /= np.max(np.abs(Q))
                self.node.prior = Q
            mask = m.ravel()
            move = self.node.select(mask)
            x, y = move // self.size, move % self.size
            assert(fst[(x, y)] == False and m[(x, y)] == False)
            fst[x, y] = True
            m[x, y] = True
            self.nr_moves += 1
            win_condition, _ = self.rules.check_win((x, y), fst)
            if win_condition:
                self.reward = 1.0
                self.termination = True
            if np.all(m):
                self.reward = 0.5
                self.termination = True
            expand = False
            if self.node.children[move] == None:
                # expand
                self.node.children[move] = MonteCarloTree(self.size)
                expand = True
            self.trace.append(self.node.children[move])
            self.node = self.node.children[move]
            self.node.total += 1.0
            if self.termination == True:
                self.state = MonteCarloExploer.state_backpropagation
            elif expand:
                self.state = MonteCarloExploer.state_simulation
            else:
                self.state = MonteCarloExploer.state_select
            self.board = snd, fst, m
        elif self.state == MonteCarloExploer.state_backpropagation:
            if self.nr_moves % 2 == 1:
                self.reward = 1.0 - self.reward
            for i in self.trace:
                i.reward += self.reward
                self.reward = 1.0 - self.reward
            self.state = MonteCarloExploer.state_select
            self.reinitialize()
        elif self.state == MonteCarloExploer.state_simulation:
            self.pending_state = np.stack(self.board, axis = -1)
            self.move  = None
            self.state = MonteCarloExploer.state_waitfor_move
            return_value = 1
        elif self.state == MonteCarloExploer.state_waitfor_move:
            if self.move != None:
                fst, snd, m = self.board
                if random.random() < FLAGS.mcts_epsilon:
                    while True:
                        m = self.board[0] + self.board[1]
                        move = random.randint(0, self.size ** 2 - 1)
                        move = move // self.size, move % self.size
                        if m[move] == False:
                            break
                else:
                    move = self.move // self.size, self.move % self.size
                self.move = None
                fst[move] = True
                m[move] = True
                self.nr_moves += 1
                termination = False
                win_condition, _ = self.rules.check_win(move, fst)
                if win_condition:
                    self.reward = 1.0
                    termination = True
                if np.all(m):
                    self.reward = 0.5
                    termination = True
                if termination:
                    self.state = MonteCarloExploer.state_backpropagation
                else:
                    self.state = MonteCarloExploer.state_simulation
                self.board = snd, fst, m
        return return_value

class MontecarloAgent(Agent):
    def __init__(self, size, session, scope, threads):
        assert(threads == 1)
        super().__init__(size, session, scope, threads)
        self.network = Network(self.size, self.scope + '/q', self.session, True)
        self.network_restored = False
        self.board = None
    def clear(self):
        super().clear()
        if self.network_restored == False:
            assert(self.network != None)
            self.network.restore()
            self.network_restored = True
        self.board = []
        self.board.append(np.zeros((self.size, self.size), dtype=np.bool_))
        self.board.append(np.zeros((self.size, self.size), dtype=np.bool_))
    def name(self):
        return "M"
    def self_move(self, thread):
        tree = MonteCarloTree(self.size)
        exploers = []
        for i in range(FLAGS.montecarlo_parallelism):
            exploers.append(MonteCarloExploer(self.size, self.board, tree, self.network))
        wait = 0
        games = 0
        steps = 0
        while games < FLAGS.montecarlo_totalsteps:
            for exploer in exploers:
                wait += exploer.step()
                if exploer.state == MonteCarloExploer.state_backpropagation:
                    games += 1
                steps += 1
                if steps >= FLAGS.montecarlo_parallelism and wait > 0:
                    steps = 0
                    inputs = []
                    exp = []
                    for e in exploers:
                        if e.pending_state is not None:
                            inputs.append(e.pending_state)
                            exp.append(e)
                            e.pending_state = None
                            wait -= 1
                    assert(wait == 0)
                    moves, Q = DqnAgent.select(inputs, self.network)
                    for m, e in zip(moves, exp):
                        assert(e.move == None)
                        e.move = m
        max = 0.0
        move = None
        tot = 0.0
        for i, c in enumerate(tree.children):
            if c == None:
                continue
            if c.total > max:
                max = c.total
                move = i
        assert(move != None)
        move = move // self.size, move % self.size
        self.board[0][move] = True
        return move
    def opponent_move(self, move, thread):
        self.board[1][move] = True

class DqntestAgentOne(DqnAgent):
    def __init__(self, size, session, scope, threads):
        super().__init__(size, session, scope, 0)
        self.epsilon = FLAGS.test_epsilon
        self.q_network = None
    def self_move(self, thread):
        return super().self_move(thread)
    def init_network(self, network):
        self.q_network = network
    def name(self):
        return "#"

class DqntestAgent(Agent):
    def __init__(self, size, session, scope, threads):
        super().__init__(size, session, scope, threads)
        self.scopes = self.scope.split(",")
        self.agents = []
        self.networks = []
        for i, scope in enumerate(self.scopes):
            self.agents.append([])
            q_network = Network(self.size, scope + '/q', self.session, True)
            self.networks.append(q_network)
            for _ in range(self.threads):
                agent = DqntestAgentOne(size, session, scope, 0)
                agent.init_network(q_network)
                self.agents[i].append(agent)
        self.active = None
        self.network_restored = False
        self.q = None
    def set_autoresolve(self, resolve):
        for i in self.agents:
            for j in i:
                j.autoresolve = resolve
    def name(self):
        return "A" + self.scope
    def opponent_move(self, position, thread):
        agent = self.active[thread]
        agent.opponent_move(position, thread)
    def self_move(self, thread):
        agent = self.active[thread]
        if agent.buffered_move == None:
            inputs = []
            for i in self.active:
                inputs.append(np.stack(i.board, axis = -1))
            m, Q = DqnAgent.select(inputs, agent.q_network)
            for a, move, q in zip(self.active, m, Q):
                a.buffered_move = (move, q)
        move, self.q = agent.self_move(thread)
        agent.buffered_move = None
        return move
    def get_values(self):
        if FLAGS.display_AI:
            return self.q.reshape([-1])
        else:
            return []
    def finish(self, result, thread):
        agent = self.active[thread]
        return agent.finish(result, thread)
    def clear(self):
        super().clear()
        self.active = random.sample(self.agents, 1)[0]
        if self.active != None:
            for agent in self.active:
                agent.clear()
        if self.network_restored == False:
            for network in self.networks:
                network.restore()
            self.network_restored = True
    def info(self):
        pass

class CloneNetworks:
    def __init__(self, size, session):
        self.session = session
        self.src = Network(size, FLAGS.copy_from + '/q', session, readonly= True)
        self.dst = Network(size, FLAGS.copy_to + '/q', session, readonly = False)
        self.copynetwork = CopyNetwork(self.src, self.dst)
    def copy(self):
        self.src.restore()
        self.copynetwork.copy(self.session)
        self.dst.save()

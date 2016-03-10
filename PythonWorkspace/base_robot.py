"""
Path follower test
Romain Chiappinelli
04.03.16
"""
import abc
import vrep #import library for VREP API
import time
import math
import numpy as np #array library
import matplotlib.pyplot as plt #used for image plotting
import signal
import threading

from idash import IDash
from robot_helpers import vomega2bytecodes, ThetaRange, v2Pos
from plot_helpers import plotVector

z = 0.027536552399396896 # z-Position of robot

class GracefulKiller:
    kill_now = False
    def __init__(self):
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self,signum, frame):
        self.kill_now = True

class BaseRobotRunner(object):
    __metaclass__ = abc.ABCMeta

    def __init__(self, color, number, clientID=None, ip='127.0.0.1'):
        """
        color: i.e. 'Blue'
        number: i.e. 1
        clientID: Default None; if provided as parameter,
            `vrep.simxStart` was called outside this class
        """
        # parameter init
        self.ip = ip
        self.bot_name = '%s%d' % (color, number)
        self.bot_nameStriker = 'Red1'

        # run startup methods
        if clientID is not None:
            # Use existing clientID (multi robot case)
            self.clientID = clientID
            self.multirobots = True
            print("ClientID obtained as parameter! (Probably doing Multirobots...)")
        else:
            # Make connection to VREP client (single robot case)
            self.initializeVrepClient()
            self.multirobots = False
        self.initializeVrepApi()
        #self.killer = GracefulKiller()
        self.idash = IDash(framerate=0.05)

    def exploreClassAttributes(self):
        for variable_name, variable_value in self.__dict__.iteritems():
            locals()[self.bot_name + "_" + variable_name] = variable_value
        # delete so there are no duplicate variables in the variable explorer
        del(variable_name)
        del(variable_value)
        return # Place Spyder Breakpoint on this Line!

    def initializeVrepClient(self):
        """ Initialization for Python to connect to VREP.
        We obtain a clientID after connecting to VREP, which is saved to
            `self.clientID`
        This method is only called if we controlling one robot with the remote API
        """
        print 'Python program started'
        count = 0
        num_tries = 10
        while count < num_tries:
            vrep.simxFinish(-1) # just in case, close all opened connections
            self.clientID=vrep.simxStart(self.ip,19999,True,True,5000,5) #Timeout=5000ms, Threadcycle=5ms
            if self.clientID!=-1:
                print 'Connected to V-REP'
                break
            else:
                "Trying again in a few moments..."
                time.sleep(3)
                count += 1
        if count >= num_tries:
            print 'Failed connecting to V-REP'
            vrep.simxFinish(self.clientID)

    def initializeVrepApi(self):
        # initialize bot handles and variables
        _, self.leftMotor=vrep.simxGetObjectHandle(
            self.clientID, '%s_leftJoint' % self.bot_name, vrep.simx_opmode_oneshot_wait)
        _, self.rightMotor=vrep.simxGetObjectHandle(
            self.clientID, '%s_rightJoint' % self.bot_name, vrep.simx_opmode_oneshot_wait)
        _, self.bot=vrep.simxGetObjectHandle(
            self.clientID, self.bot_name, vrep.simx_opmode_oneshot_wait)
        _, self.ball=vrep.simxGetObjectHandle(
            self.clientID, 'Ball', vrep.simx_opmode_oneshot_wait)

        # proxSens = prox_sens_initialize(self.clientID)
        # initialize odom of bot
        _, self.xyz = vrep.simxGetObjectPosition(
            self.clientID, self.bot, -1, vrep.simx_opmode_streaming)
        _, self.eulerAngles = vrep.simxGetObjectOrientation(
            self.clientID, self.bot, -1, vrep.simx_opmode_streaming)

        # FIXME: striker handles shouldn't be part of the default base class
        # FIXME: should be better way to have information regarding all the bots (Central Control?) (Publishers/Subscribers...)?
        # initialize bot handles and variables for Red1
        _, self.leftMotorStriker=vrep.simxGetObjectHandle(
            self.clientID, '%s_leftJoint' % self.bot_name, vrep.simx_opmode_oneshot_wait)
        _, self.rightMotorStriker=vrep.simxGetObjectHandle(
            self.clientID, '%s_rightJoint' % self.bot_name, vrep.simx_opmode_oneshot_wait)
        _, self.botStriker = vrep.simxGetObjectHandle(
            self.clientID, self.bot_nameStriker, vrep.simx_opmode_oneshot_wait)
        _, xyzStriker = vrep.simxGetObjectPosition(
            self.clientID, self.botStriker, -1, vrep.simx_opmode_streaming)
        _, eulerAnglesStriker = vrep.simxGetObjectOrientation(
            self.clientID, self.botStriker, -1, vrep.simx_opmode_streaming)
        # get ball position
        _, ballxyz = vrep.simxGetObjectPosition(
            self.clientID, self.ball, -1, vrep.simx_opmode_streaming)

    @abc.abstractmethod
    def robotCode(self):
        """ OUR ROBOT CODE GOES HERE """
        return

    def getRobotConf(self, robot_handle):
        _, xyz = vrep.simxGetObjectPosition(
            self.clientID, robot_handle, -1, vrep.simx_opmode_buffer)
        _, eulerAngles = vrep.simxGetObjectOrientation(
            self.clientID, robot_handle, -1, vrep.simx_opmode_buffer)
        x, y, z = xyz
        theta = eulerAngles[2]

        return (x, y, theta)

    def getBallPose(self):
        _, xyz = vrep.simxGetObjectPosition(
            self.clientID, self.ball, -1, vrep.simx_opmode_streaming)
        x, y, z = xyz
        return (x, y)

    def setMotorVelocities(self, forward_vel, omega):
        ctrl_sig_left, ctrl_sig_right = vomega2bytecodes(forward_vel, omega, g=1)
        _ = vrep.simxSetJointTargetVelocity(
            self.clientID,self.leftMotor,ctrl_sig_left,vrep.simx_opmode_oneshot_wait) # set left wheel velocity
        _ = vrep.simxSetJointTargetVelocity(
            self.clientID,self.rightMotor,ctrl_sig_right,vrep.simx_opmode_oneshot_wait) # set right wheel velocity

    def followPath(self, robotConf, v = 20, r=0.05):
        """ velocity of the robot, radius of the buffer zone
        """
        robotpos = np.array(robotConf)[0:2]
        while self.path.shape[1]>1 and np.linalg.norm(robotpos - self.path[:,0])<r :
            self.path = self.path[:, 1:]  # remove first node
        if self.path.shape[1]==1 and np.linalg.norm(robotpos - self.path[:,0])<r :
            self.setMotorVelocities(0, 0)
        else:
            vRobot = v2Pos(robotConf, self.path[:,0])
            self.setMotorVelocities(vRobot[0], vRobot[1])

    def unittestMoveForward(self):
        self.setMotorVelocities(forward_vel=1, omega=0)

    def unittestTurnSideways(self, not_first_time):
        x, y, theta = self.getRobotPose()
        if not_first_time:
            goal_theta = self.first_theta + np.pi / 2
            print goal_theta
            error_theta = ThetaRange.angleDiff(theta, goal_theta)

            # control
            omega = 10 * error_theta
            print omega
            self.setMotorVelocities(0, omega)

            # visualization
            def plotCurrentDesiredHeadings():
                plotVector(ThetaRange.pol2cart(1, theta), 'k')
                plotVector(ThetaRange.pol2cart(1, goal_theta), 'r')
            self.idash.add(plotCurrentDesiredHeadings)
            self.idash.plotframe()
        else:
            self.first_theta = theta

    def clean_exit(self):
        vrep.simxFinish(self.clientID)
        print 'Program ended'

    def run(self):
        if self.clientID!=-1:
            if not self.multirobots:
                # Start simulation if MultiRobotRunner not already starting it
                _ = vrep.simxStartSimulation(self.clientID,vrep.simx_opmode_oneshot_wait)
            self.robotCode()

        if not self.multirobots:
            # Stop VREP simulation cleanly if MultiRobotRunner not already stopping it
            self.clean_exit()

    def displayPath(self):
        print('path=')
        for i in range(0, self.path.shape[1]):
            print('%f, %f' % (self.path[0, i], self.path[1, i]))

class MultiRobotRunner(object):
    """
    MultiRobotRunner implements similar methods to BaseRobotRunner for the
    starting, running, and exiting of VREP robots.

    Using the addRobot method, one can add BaseRobotRunners to the
    MultiRobotRunner.

    MultiRobotRunner in its `run` method will create separate threads for the
    different robot's `robotCode` methods.

    It will then wait until all threads have finished before exiting


    This code relies on threads in Python, more which can be learned here:
    https://pymotw.com/2/threading/
    """

    def __init__(self, ip='127.0.0.1'):
        # start vrep to obtain a self.clientID
        self.ip = ip
        self.initializeVrepClient()
        self.bots = []

    def initializeVrepClient(self):
        #Initialisation for Python to connect to VREP
        print 'Python program started from MultiRobotRunner'
        count = 0
        num_tries = 10
        while count < num_tries:
            vrep.simxFinish(-1) # just in case, close all opened connections
            self.clientID=vrep.simxStart(self.ip,19999,True,True,5000,5) #Timeout=5000ms, Threadcycle=5ms
            if self.clientID!=-1:
                print 'Connected to V-REP'
                break
            else:
                "Trying again in a few moments..."
                time.sleep(3)
                count += 1
        if count >= num_tries:
            print 'Failed connecting to V-REP'
            vrep.simxFinish(self.clientID)

    def clean_exit(self):
        vrep.simxFinish(self.clientID)
        print 'Program ended'

    def addRobot(self, instance):
        self.bots.append(instance)

    def run(self):
        if self.clientID!=-1:
            _ = vrep.simxStartSimulation(self.clientID,vrep.simx_opmode_oneshot_wait)
            # Create threads for each
            self.threads = []
            for bot in self.bots:
                # Robot Thread
                t = threading.Thread(
                      name="%sThread" % bot.bot_name
                    , target=bot.robotCode)
                t.setDaemon(True) # Require it to join!
                self.threads.append(t)
                t.start()
                print("Started robotCode for %s" % bot.bot_name)

        # Require threads to join before exiting
        for t in self.threads:
            t.join()
        self.clean_exit()

if __name__ == '__main__':
    class MyRobotRunner(BaseRobotRunner):

        def __init__(self, *args, **kwargs):
            super(MyRobotRunner, self).__init__(*args, **kwargs)

        def robotCode(self):

            self.path = np.array([[0.3, 0.3, -0.3, -0.3],
                                  [0.4, -0.4, -0.4, 0.4]])
            while 1:
                robotConf = self.getRobotConf(self.bot)
                self.followPath(robotConf)
#                robotConf = self.getRobotConf(self.bot)
#                print('robotConf.x=%f' % robotConf[0])
#                print('robotConf.y=%f' % robotConf[1])
#                print('robotConf.theta=%f' % robotConf[2])
#                ballPos = self.getBallPose() # (x, y)
#                print('ballPos.x=%f' % ballPos[0])
#                print('ballPos.y=%f' % ballPos[1])
#                vRobot = v2Pos(robotConf, ballPos)
#                print('vRobot.x=%f' % vRobot[0])
#                print('vRobot.y=%f' % vRobot[1])
#                self.setMotorVelocities(vRobot[0], vRobot[1])
#            time.sleep(3)

    obj = MyRobotRunner('Blue', 1)
    obj.run()

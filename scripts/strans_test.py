from contextlib import contextmanager
import os
import glob
import shutil
import time as ttime

import ophyd.controls.areadetector.detectors as ad
import ophyd.controls.positioner as ocp
import ophyd.controls.signal as osc

from nose.tools import assert_true
import numpy as np
import pandas as pd

# define the motors
rot = ocp.EpicsMotor('XF:21IDC-ES{SH:proto-Ax:R}Mtr.VAL', 
                     name='rot')

claw = ocp.EpicsMotor('XF:21IDC-ES{SH:proto-Ax:C}Mtr', 
                      name='claw')
manip = ocp.EpicsMotor('XF:21IDC-ES{SH:proto-Ax:T}Mtr', 
                       name='manip')

feed = ocp.EpicsMotor('XF:21IDC-ES{SH:proto-Ax:F}Mtr', 
                      name='feed')

# camera
cam = ad.ProsilicaDetector('ESM:')

# binary switches
_gpio_pv = 'XF:21IDC-CT{MC:01}In:GPIO-Sts'
B0 = osc.EpicsSignal(_gpio_pv+'.B0', name='B0')
B1 = osc.EpicsSignal(_gpio_pv+'.B1', name='B1')
B2 = osc.EpicsSignal(_gpio_pv+'.B2', name='B2')
B3 = osc.EpicsSignal(_gpio_pv+'.B3', name='B3')
B4 = osc.EpicsSignal(_gpio_pv+'.B4', name='B4')
B5 = osc.EpicsSignal(_gpio_pv+'.B5', name='B5')


@contextmanager
def rolling_record_motion(fp, run_number, buffer_len=10):
    """
    This context manager is for collecting a series of movies
    in a rolling buffer.  This assumes that the current path that
    the file plugin has in '/true/base/path/NN'.  The files will be
    saved into '/true/base/path/(run_number % buffer_len)'.

    Any files in the output folder which match the file template glob
    will be deleted prior to capturing any new data.


    Parameters
    ----------
    fp : FilePlugin
        The file plugin of the camera to use.  Must have tiff file
        support.  It is assumed that all of the exposure details,
        basepath, template, ect have been set before hand.

    run_number : int
        The run number, used to compute where to save the files

    buffer_len : int, optional
        The number of past movies to keep
       
    """
    fp.enable.value = False
    base_path = os.path.dirname(fp.file_path.value.rstrip('/'))

    new_path = os.path.join(base_path, 
                            '{:02d}'.format(run_number % buffer_len))
    os.makedirs(new_path, exist_ok=True)
    fp.file_path.value = new_path
    
    # this assumes that the fname pattern is more-or-less
    # %s%s_%d.ext % (path, name, number)

    exist_glob = os.path.join(new_path, fp.file_name.value) + '*'

    # remove any existing files
    for f in glob.iglob(exist_glob):
        os.unlink(f)
    fp.file_number = 0
    fp.enable.value = True
    try:
        yield
    except Exception as e:
        raise e
    finally:
        fp.enable.value = False

        
class ESM_Robot:
    def __init__(self, feed, claw, manip):
        # eventually this will have buckets of state
        # dictionary mapping the feed socket numbers to motor
        # positions
        self.pos_map = {0: 0, 1:5.5}
        self.feed = feed
        self.claw = claw
        self.manip = manip

    @property
    def has_sample(self):
        """If the claw is holding a sample
        
        """
        # eventually, this should read from the IO pv
        return False

    def put_in_pos(self, n):
        """Put sample in position n

        Assuming the claw has a sample grasped, put it 
        in the given position
        """
        if not self.has_sample:
            raise RuntimeError("Claw does not have sample")
        self.set_feed(n)
        # move arm forward
        # release claw
        pass

    def set_feed_pos(self, n):
        """Put position n in a place where the claw can reach
        
        
        """
        self.feed.set(self.pos_map[n], wait=True)


def simple_rotation():
    """Simple test
    
    Rotates claw from 0 deg to 5 deg and back to 0.
    """
    rot.set(0, wait=True)
    rot.set(5, wait=True)
    
    rot.set(0, wait=True)


def run_test(func, count, record_file, fp, fname='claw', 
             buffer_len=10, cleanup=False):
    """Test transfer reliability

    This is a helper function to manage the repeatedly running
    a test function to test the behavior of the sample transfer
    functionality.  This function manages:
    
      - repeatedly calling the test function
      - recording the number of success/failure
      - managing a rolling buffer of movies of the transfer

    Parameters
    ----------
    func : callable
        The function to call many times, must take no arguments ::
           
           def func():
               pass
               
        The return value is ignored.  To indicate failure the test
        function should raise an exception.

    count : int
        The number of time to call the test function

    record_file : str
        Path to csv file to append results to.  The columns of
        the csv must be [count,success,fail] which are the number
        of time it was told to run, the number of successes and the
        number of failures (which will always be 0 or 1).

    fp : ophyd.controls.areadetector.plugins.FilePlugin
        The file plugin of the camera to use for recording video of
        the transfer.

        The movies will be saved in folders called ``movies_NNNNN`` in
        the same directory as ``record_file``.  These files can optionally
        be removed if all call to the test function succeed.

    fname : str, optional
        Prefix to use in naming saved images.  Defaults to 'claw'

    buffer_len : int, optional
        The number of movies before a failed test to save.  This is
        implemented as a rolling buffer of folders in the ``movies_*``
        folders.  Defaults to 10

    cleanup : bool, optional
        If movies from fully successful runs should be deleted.  Defaults
        to `False`
    """
    record_file = os.path.abspath(record_file)
    run_number = 0
    with open(record_file, 'r') as fin:
        # skip one line of header
        next(fin)
        for l in fin:
            run_number += 1
    
    base_path = os.path.join(os.path.dirname(record_file), 
                             'movies'
                             '{:05d}'.format(run_number))
    os.makedirs(base_path, exist_ok=True)
    fp.file_path = os.path.join(base_path, '00')
    _fail_count = 0
    while fp.file_path.value.rstrip('/') != os.path.join(base_path, '00'):
        ttime.sleep(.1)
        _fail_count += 1
        if _fail_count > 5:
            raise RuntimeError("took half a second and file_path "
                               "still not set right. "
                               "EPICS is broken")

    fp.file_name = fname
    success_count = 0
    fail = 1
    try:
        for j in range(count):
            print("starting round {j} of {c}".format(j=j, c=count))
            with rolling_record_motion(fp, j, buffer_len=buffer_len):
                func()
            success_count += 1
    except (Exception, ) as e:
        print(repr(e))
    except KeyboardInterrupt:
        print("\ncanceled by user")
    else:
        fail = 0
        # clean up files if we succedded
        if cleanup:
            shutil.rmtree(base_path)
    finally:
        with open(record_file, 'a') as fout:
            fout.write('{:d},{:d},{:d}\n'.format(count, success_count, fail))
        if fail:
            movie_order = np.mod(np.arange(max(success_count - 10 +1, 0), 
                                    success_count + 1), buffer_len)[::-1]
            movie_loc = '\n '.join(os.path.join(base_path, '{:02d}'.format(j))
                                  for j in movie_order)
            print("Told to run {count} succeded {suc} times before failing\n"
                  "last {buf_len} movies are in: \n "
                  "{mp}\nnewest first.".format(count=count, 
                                suc=success_count,
                                buf_len=buffer_len,
                                mp=movie_loc)
                  )
        else:
            print("Last {success_count} runs succedded "
                  "without failure".format(success_count=success_count))

def compute_num_between_failures(fname):
    """Compute reliability of transfer from CSV

    This is a helper function to process the number of successful
    transfers between failures.

    It assumes that the input CSV has at least the columns 'fail' and
    'success'.  Each row is the output of a single `run_test`
    invocation The 'success' column is the number of time the test ran
    before a failure and the 'fail' column has a 1 if there was a test
    failure and 0 otherwise.

    Parameters
    ----------
    fname : str
        Path to CSV file.  Expected structure described above.

    Returns : pd.Series

        The number of successful trials between each failure.  Last
        and first entries may be unreliable due to edge effects (no
        observed previous failure for first number, and does not
        currently indicate of the last `run_test` run ended in failure
        or not)

    """
    df = pd.read_csv(fname)
    df['fail_index'] = df.fail.cumsum()
    return df.groupby('fail_index').sum().success

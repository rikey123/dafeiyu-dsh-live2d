"""Contain a Windows service before its interpreter can spawn CUDA workers.

Use maintained pywin32 APIs. Assigning a running venv launcher to a job races
its real interpreter, so creation must be suspended until containment succeeds.
"""
from __future__ import annotations

import msvcrt
import subprocess

import win32api
import win32con
import win32event
import win32job
import win32process


class NativeProcess:
    """Small Popen lifecycle interface for a process created by Win32."""
    def __init__(self, handle, pid, command):
        self.handle, self.pid, self.args = handle, pid, command
        self.returncode = None

    def poll(self):
        if self.returncode is None and win32event.WaitForSingleObject(self.handle, 0) == win32event.WAIT_OBJECT_0:
            self.returncode = win32process.GetExitCodeProcess(self.handle)
            self.handle.Close()
            self.handle = None
        return self.returncode

    def wait(self, timeout=None):
        if self.poll() is None:
            duration = win32event.INFINITE if timeout is None else max(0, int(timeout * 1000))
            if win32event.WaitForSingleObject(self.handle, duration) == win32event.WAIT_TIMEOUT:
                raise subprocess.TimeoutExpired(self.args, timeout)
            self.poll()
        return self.returncode

    def terminate(self):
        if self.poll() is None:
            try:
                win32process.TerminateProcess(self.handle, 1)
            except win32api.error:
                if self.poll() is None:
                    raise

    kill = terminate


def start_native_process(command, *, cwd, env, log):
    job = win32job.CreateJobObject(None, "")
    process, thread, log_handle, input_handle = None, None, None, None
    try:
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        current = win32api.GetCurrentProcess()
        log_handle = win32api.DuplicateHandle(current, msvcrt.get_osfhandle(log.fileno()), current,
                                             0, True, win32con.DUPLICATE_SAME_ACCESS)
        with open("NUL", "rb") as null:
            input_handle = win32api.DuplicateHandle(current, msvcrt.get_osfhandle(null.fileno()), current,
                                                   0, True, win32con.DUPLICATE_SAME_ACCESS)
        startup = win32process.STARTUPINFO()
        startup.dwFlags |= win32con.STARTF_USESTDHANDLES
        startup.hStdInput, startup.hStdOutput, startup.hStdError = input_handle, log_handle, log_handle
        handle, thread, pid, _ = win32process.CreateProcess(
            command[0], subprocess.list2cmdline(command), None, None, True,
            win32con.CREATE_SUSPENDED | win32con.CREATE_NO_WINDOW, dict(env), str(cwd), startup)
        process = NativeProcess(handle, pid, command)
        win32job.AssignProcessToJobObject(job, handle)
        win32process.ResumeThread(thread)
        return process, job
    except Exception as error:
        job.Close()
        if process is not None:
            process.kill()
            process.wait(timeout=5)
        raise OSError("Could not start contained native voice service") from error
    finally:
        for handle in (thread, log_handle, input_handle):
            if handle is not None:
                handle.Close()

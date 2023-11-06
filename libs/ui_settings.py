"""
    Module for setting different ui options on Android devices
    """

from . import logger as l
import os

log = l.get_logger(f"{os.path.basename(__file__)}")


def press_power_button(exc):
    """
    Input the key event of the power button

    :param exc: connected executor to send commands
    :type exc: executor
    """
    log.info("Pressing power button")
    exc.run("input keyevent KEYCODE_POWER")


def is_screen_on(exc):
    """
    Check if the screen is on

    :param exc: connected executor to send commands
    :type exc: executor
    :return: True if screen is on, False if screen is off
    :rtype: boolean
    """
    mHolding = exc.run("dumpsys deviceidle get screen")
    if 'true' not in mHolding:
        log.info("Screen is off")
        return False
    log.info("Screen is on")
    return True


def get_screen_settings(exc):
    """Gets the current screen settings

    :param exc: connected executor to send commands
    :type exc: executor
    :return: list of [screen_brightness_level, screen_timeout (seconds)]
    :rtype: list [int, int]
    """
    cur_bright_level = exc.run(
        "settings get system screen_brightness").strip()
    cur_screen_timeout = exc.run(
        "settings get system screen_off_timeout").strip()
    return [int(cur_bright_level), int(cur_screen_timeout)]


def set_screen_settings(exc, screen_brightness=200, screen_timeout=1800000):
    """Sets the screen brightness and timeout to given parameters

    :param exc: connected executor to send commands
    :type exc: executor
    :param screen_brightness: 0-200 value for screen brightness, defaults to 200
    :type screen_brightness: int, optional
    :param screen_timeout: 0-1800000 value for screen timeout in micro-seconds, defaults to 1800000
    :type screen_timeout: int, optional
    """
    log.info(f"Setting screen brightness to {screen_brightness}")
    exc.run(
        f"settings put system screen_brightness {screen_brightness}")
    log.info(
        f"Setting screen timeout to {screen_timeout / 60000} mins")
    exc.run(
        f"settings put system screen_off_timeout {screen_timeout}")
    # check the settings have been changed
    if get_screen_settings(exc) == [screen_brightness, screen_timeout]:
        return True
    return False


def get_idle_state(exc, deep=False) -> bool:
    """
    Return if the device is in idle state

    :param exc: connected executor
    :type exc: executor
    :return: True if the device is in idle False if the device is active
    :rtype: bool
    """
    cmd = "dumpsys deviceidle enabled"
    if deep:
        cmd = cmd+" deep"
    idle_state = exc.run("dumpsys deviceidle enabled").strip()
    if idle_state == "1":
        return True
    return False


def enable_idle_state(exc) -> None:
    """
    Turn on deviceidle

    :param exc: connected executor
    :type exc: executor
    """
    log.info("Putting device into light idle mode")
    exc.run("dumpsys deviceidle enable")
    if not get_idle_state(exc):
        raise RuntimeError("Failed to put device in idle mode")


def disable_idle_state(exc) -> None:
    """
    Return if the device is in idle state

    :param exc: connected executor
    :type exc: executor
    :return: True if the device is in idle False if the device is active
    :rtype: bool
    """
    log.info("Putting device into active mode")
    exc.run("dumpsys deviceidle disable")
    if get_idle_state(exc):
        raise RuntimeError("Failed to bring device out of idle mode")

def force_idle_state(exc) -> None:
    """
    Set device under test to deep idle state

    :param exc: connected executor
    :type exc: executor
    """
    enable_idle_state(exc)
    log.info("Putting device into deep idle mode")
    exc.run("dumpsys deviceidle force-idle")
    if not get_idle_state(exc, deep=True):
        raise RuntimeError("Failed to put device in deep idle mode")


def get_bt_discoverable(exc) -> None:
    """
    Clicks on Allow on the terminal screen to make bluetooth discoverable

    :param exc: connected executor
    :type exc: excutor
    """
    log.info("Get bluetooth into discoverable mood")
    #first tab which tabs on Deny button on terminal screen
    exc.run('input keyevent KEYCODE_TAB')
    #second tab goes to Allow button on terminal screen
    exc.run('input keyevent KEYCODE_TAB')
    #enter keyevent, it clicks on Allow on screen
    exc.run('input keyevent KEYCODE_ENTER')

    #check if bt is now discoverable
    ScanMode = exc.run("dumpsys bluetooth_manager | sed -n '/AdapterProperties/,/^$/p' | grep ScanMode:").replace("ScanMode: ","")
    if "SCAN_MODE_CONNECTABLE_DISCOVERABLE" in ScanMode:
        log.info("Bluetooth is in discoverable mode")
    else:
        raise RuntimeError("Failed to make bluetooth discoverable")




    
    
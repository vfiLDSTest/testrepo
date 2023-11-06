#!/usr/env/python3
# Importing relevant libs
from  libs import executor, logger, env_settings
from  libs.config_parser import ConfigParser
import time


class TestCase():





    def test_hqa_app_pscr(self):
        # Instantiating the excutor module
        exc = executor.get_executor('root', False, 30)
        log = logger.get_logger(__name__)
        log.debug("echo starting HQA app")
        while True:
            # wake screen
            exc.run("input keyevent KEYCODE_WAKEUP")
            # Send the command to start the android HQA test app
            start_app = exc.run(f"am start com.verifone.hqa.Main/com.verifone.hqa.app.presentation.Main.MainActivity")
            # To get info about the response from the device whilenstarting the app
            log.info(f"response: {start_app}")
            time.sleep(3)
            # To select the Device from the HQA app
            select_device = exc.run(f"input tap 378 193")
            time.sleep(0.5)
            exc.run(f"input tap 318 211")
            time.sleep(0.5)
            # To select the Project from the HQA app
            select_project = exc.run(f"input tap 356 263")
            time.sleep(0.5)
            exc.run(f"input tap 312 647")
            time.sleep(0.5)
            # To scrol down and select the PSCR test option
            select_pscr = exc.run(f"input swipe 261 511 295 33 20")
            time.sleep(1.5)
            exc.run(f"input tap 176 540")
            time.sleep(0.5)
            # To select the Loop time as 1 loop 

            exc.run(f"input tap 641 325")
            time.sleep(0.5)
            exc.run(f"input tap 985 604")
            time.sleep(0.5)
            exc.run(f"input tap 247 431")
            time.sleep(0.5)
            exc.run(f"input tap 971 682")
            time.sleep(0.5)
            exc.run(f"input tap 636 476")
            time.sleep(5)
            exc.run(f"input tap 610 168")
            time.sleep(0.5)
            start_stop = exc.run(f"am force-stop com.verifone.hqa.Main")
            time.sleep(4)
        


        
        

    
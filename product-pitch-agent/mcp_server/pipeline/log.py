
# Copyright 2025 Google LLC

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     https://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from loguru import logger

from mcp_server.pipeline.config import settings


if TYPE_CHECKING:
    import loguru


class Logger:
    def __init__(self):
        self.log_path = settings.LOG_DIR
        os.makedirs(self.log_path, exist_ok=True)

    def log(self) -> loguru.Logger:
        log_stdout_file = os.path.join(self.log_path, settings.LOG_STDOUT_FILENAME)
        log_stderr_file = os.path.join(self.log_path, settings.LOG_STDERR_FILENAME)

        log_config = dict(rotation='10 MB', retention='15 days', compression='tar.gz', enqueue=True)

        # stdout
        logger.add(
            log_stdout_file,
            level='INFO',
            filter=lambda record: record['level'].name == 'INFO' or record['level'].no <= 25,
            **log_config,
            backtrace=False,
            diagnose=False,
        )
        # stderr
        logger.add(
            log_stderr_file,
            level='ERROR',
            filter=lambda record: record['level'].name == 'ERROR' or record['level'].no >= 30,
            **log_config,
            backtrace=True,
            diagnose=True,
        )

        return logger


log = Logger().log()

"""Central application logging for Evidence Gate case24."""
import logging
from .structured_logging import _file_logger, _redact, _safe_exception


class _RuntimeFormatter(logging.Formatter):
    def format(self,record):
        line=f'{record.levelname} | {record.name} | {_redact(record.getMessage())}'
        return f'{line} | {_safe_exception(record.exc_info)}' if record.exc_info else line

def get_logger(path: str="logs/evidence_gate_case24.log") -> logging.Logger:
    return _file_logger(path,'runtime',_RuntimeFormatter())

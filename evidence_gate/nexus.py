"""NEXUS 계통수 파일에서 끝 이름(tip label) 목록을 읽는다.

TREES 블록의 translate 목록 순서를 기준 식별자 순서로 쓴다. translate가 없으면 TAXA 블록의
TAXLABELS를 쓴다. 트리 문자열의 끝 번호가 translate 번호와 다르면 멈춘다.
"""

from __future__ import annotations

import re


class NexusError(ValueError):
    pass


def _label(token):
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] == "'":
        return token[1:-1].replace("''", "'")
    return token


def tip_labels(text):
    body = re.sub(r"\[[^\]]*\]", "", text)  # NEXUS 주석 제거
    if not body.lstrip().upper().startswith("#NEXUS"):
        raise NexusError("#NEXUS 머리말이 없음")
    translate = re.search(r"\btranslate\b(.*?);", body, re.IGNORECASE | re.DOTALL)
    if translate:
        numbers, labels = [], []
        for entry in translate.group(1).split(","):
            parts = entry.strip().split(None, 1)
            if len(parts) != 2 or not parts[0].isdigit():
                raise NexusError(f"translate 항목 형식 오류: {entry.strip()[:60]!r}")
            numbers.append(int(parts[0]))
            labels.append(_label(parts[1]))
        if numbers != list(range(1, len(numbers) + 1)):
            raise NexusError("translate 번호가 1부터 연속되지 않음")
        tree = re.search(r"\btree\b[^=]*=\s*(.*?);", body[translate.end():], re.IGNORECASE | re.DOTALL)
        if not tree:
            raise NexusError("translate 뒤에 tree 문장이 없음")
        tips = [int(n) for n in re.findall(r"[(,]\s*(\d+)\s*(?=[:,)])", tree.group(1))]
        if sorted(tips) != numbers:
            raise NexusError("트리 끝 번호와 translate 번호가 다름")
        return labels
    taxlabels = re.search(r"\btaxlabels\b(.*?);", body, re.IGNORECASE | re.DOTALL)
    if taxlabels:
        return [_label(t) for t in re.findall(r"'(?:[^']|'')*'|\S+", taxlabels.group(1))]
    raise NexusError("translate나 TAXLABELS 목록이 없음")

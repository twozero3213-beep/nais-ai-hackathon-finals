"""[0 이영] 본선 집중 시연 진입점."""
# 수정 이유: 입력·검산·사람 확인·보고서 흐름만 기본 화면으로 제공한다.
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parent / "finals" / "app.py"), run_name="__main__")

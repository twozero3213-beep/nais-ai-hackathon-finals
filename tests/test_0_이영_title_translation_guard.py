"""제목 번역 안전장치를 실제 모델·네트워크·유료 호출 없이 검사한다."""
# [작성: 0 이영 · Codex] 2026-10-01T03:04:44+09:00 — Claude가 관측한 한국어 약어 오인·반복·식별자 훼손을 재현하고 과학 약어의 번역 입력 보존을 확인한다.
import pytest

from core import title_translation as tt


def _forbid_model(monkeypatch):
    def forbidden(path):
        raise AssertionError("번역 모델을 호출하면 안 됩니다")
    monkeypatch.setattr(tt, "_model_ready", forbidden)


def test_default_off_never_bootstraps_a_model(monkeypatch):
    monkeypatch.delenv(tt.ENABLE_ENV, raising=False)
    monkeypatch.delenv("NAIS_TRANSLATION_MODEL", raising=False)
    _forbid_model(monkeypatch)
    assert not tt.enabled()
    assert tt.korean_title("Climate change impacts on crop yields") is None


def test_operator_can_explicitly_enable_translation(monkeypatch):
    monkeypatch.delenv("NAIS_TRANSLATION_MODEL", raising=False)
    monkeypatch.setenv(tt.ENABLE_ENV, "0")
    assert not tt.enabled()
    monkeypatch.setenv(tt.ENABLE_ENV, "1")
    assert tt.enabled()
    monkeypatch.delenv(tt.ENABLE_ENV)
    monkeypatch.setenv("NAIS_TRANSLATION_MODEL", "C:/models/en_ko")
    assert tt.enabled()


@pytest.mark.parametrize("switch", ["0", "1"])
@pytest.mark.parametrize("title", ["움직임의 흐름 읽는 AI 반도체 개발", "DNA 손상 복구와 BRAF V600E 변이의 관계"])
def test_korean_title_with_acronyms_is_preserved(monkeypatch, switch, title):
    monkeypatch.setenv(tt.ENABLE_ENV, switch)
    _forbid_model(monkeypatch)
    assert tt.korean_title(title) == title


@pytest.mark.parametrize("title", [
    "Профессионально-личностное развитие педагогов",
    "Sztuczna inteligencja w muzeum martyrologicznym: Model Trzech Progów",
    "日本語の論文題名", "S2C_52SBB_20260930_0_L2A",
])
def test_non_english_titles_and_identifiers_never_reach_model(monkeypatch, title):
    monkeypatch.setenv(tt.ENABLE_ENV, "1")
    _forbid_model(monkeypatch)
    assert tt.korean_title(title) is None


def test_scientific_acronyms_and_capitalisation_reach_model_verbatim(monkeypatch):
    monkeypatch.setenv(tt.ENABLE_ENV, "1")
    monkeypatch.setattr(tt, "_model_ready", lambda path: True)
    seen = []
    def translate(title, path):
        seen.append(title)
        return "BRAF V600E와 DNA 복구의 관계"
    monkeypatch.setattr(tt, "_translate", translate)
    title = "THE RELATIONSHIP BETWEEN BRAF V600E AND DNA REPAIR"
    assert tt.korean_title(title) == "BRAF V600E와 DNA 복구의 관계"
    assert seen == [title]


@pytest.mark.parametrize("output", [
    "항공 우주의 안전: " + "항공 우주 " * 12,
    "관리 관리 관리", "", None,
    "Climate change impacts on crop yields",
    "Pro-Climate Lobbying and Corporate Default Risk: 미국 회사로부터의 증거",
    "가" * 200,
])
def test_broken_outputs_are_rejected(output):
    assert tt._accept("Short title here", output) is None


def test_korean_draft_keeps_scientific_acronyms_and_latin_species_names():
    assert tt._accept("COVID-19 and AI methods compared", "COVID-19와 AI 방법의 비교") == "COVID-19와 AI 방법의 비교"
    assert tt._accept("New species (Aptenodytes patagonicus) found", "새로운 종(Aptenodytes patagonicus) 발견") == "새로운 종(Aptenodytes patagonicus) 발견"
    assert tt._accept("Comparison of methods", "인공 지능 방법의 비교") == "인공지능 방법의 비교"


# [작성: 0 이영 · Codex] 2026-10-01T03:19:13+09:00 — UI가 저장된 title_ko를 직접 읽으면 기본 꺼짐·출력 검사를 우회하던 경계를 실제 UI 어댑터로 확인한다.
def test_cached_discovery_draft_is_suppressed_when_translation_is_disabled(monkeypatch):
    from core.paper_discovery_ui import korean_title
    monkeypatch.delenv(tt.ENABLE_ENV, raising=False)
    monkeypatch.delenv("NAIS_TRANSLATION_MODEL", raising=False)
    _forbid_model(monkeypatch)
    assert korean_title("Climate change impacts on crop yields", stored_draft="기후 변화와 작물 수확량") is None


def test_cached_discovery_drafts_pass_the_same_output_guard_without_model_calls(monkeypatch):
    from core.paper_discovery_ui import korean_title
    monkeypatch.setenv(tt.ENABLE_ENV, "1")
    _forbid_model(monkeypatch)
    title = "Economic security in an aging America"
    assert korean_title(title, stored_draft="항공 우주 " * 12) is None
    assert korean_title(title, stored_draft="고령화하는 미국의 경제 안보") == "고령화하는 미국의 경제 안보"

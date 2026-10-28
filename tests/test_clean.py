import pytest

from swellsense.processing.clean import Section, clean_sections


def test_empty_input_returns_no_sections():
    assert clean_sections("") == []


def test_no_headings_is_single_lead_section():
    text = "Opening paragraph only."
    assert clean_sections(text) == [Section(heading="", text="Opening paragraph only.")]


def test_lead_section_before_first_heading():
    text = "Lead line.\n\n== First ==\nFirst body."
    assert clean_sections(text) == [
        Section(heading="", text="Lead line."),
        Section(heading="First", text="First body."),
    ]


def test_lead_section_heading_is_empty_string():
    text = "Only lead."
    result = clean_sections(text)
    assert len(result) == 1
    assert result[0].heading == ""


def test_nested_headings_levels_two_three_four():
    text = (
        "Lead.\n"
        "== Level two ==\n"
        "Two body.\n"
        "=== Level three ===\n"
        "Three body.\n"
        "==== Level four ====\n"
        "Four body."
    )
    assert clean_sections(text) == [
        Section(heading="", text="Lead."),
        Section(heading="Level two", text="Two body."),
        Section(heading="Level two > Level three", text="Three body."),
        Section(heading="Level two > Level three > Level four", text="Four body."),
    ]


@pytest.mark.parametrize(
    "heading",
    [
        "References",
        "SEE ALSO",
        " external links ",
        "Further Reading",
        "NOTES",
        "bibliography",
    ],
)
def test_dropped_boilerplate_headings_are_removed(heading: str):
    text = (
        f"== Intro ==\nKeep this.\n== {heading} ==\nDrop this.\n== After ==\nKeep too."
    )
    assert clean_sections(text) == [
        Section(heading="Intro", text="Keep this."),
        Section(heading="After", text="Keep too."),
    ]


def test_empty_section_after_normalisation_is_dropped():
    text = "== Intro ==\nText.\n== Empty ==\n   \n\n  \n== Next ==\nMore."
    assert clean_sections(text) == [
        Section(heading="Intro", text="Text."),
        Section(heading="Next", text="More."),
    ]


def test_nested_heading_under_dropped_section_is_kept():
    text = "== References ==\nRef list.\n=== Detail ===\nStill useful."
    assert clean_sections(text) == [
        Section(heading="Detail", text="Still useful."),
    ]


def test_sibling_h3s_under_one_h2_share_parent_in_path():
    text = "== Parent ==\nIntro.\n=== Child one ===\nOne.\n=== Child two ===\nTwo."
    assert clean_sections(text) == [
        Section(heading="Parent", text="Intro."),
        Section(heading="Parent > Child one", text="One."),
        Section(heading="Parent > Child two", text="Two."),
    ]


def test_h2_after_h3_pops_back_to_new_h2_path():
    text = "== A ==\nA body.\n=== B ===\nB body.\n== C ==\nC body."
    assert clean_sections(text) == [
        Section(heading="A", text="A body."),
        Section(heading="A > B", text="B body."),
        Section(heading="C", text="C body."),
    ]


def test_dropped_parent_path_omits_name_child_not_glued_to_prior_kept():
    text = "== Intro ==\nKeep.\n== References ==\nRefs.\n=== Detail ===\nNested keep."
    assert clean_sections(text) == [
        Section(heading="Intro", text="Keep."),
        Section(heading="Detail", text="Nested keep."),
    ]


def test_whitespace_normalisation():
    text = "Line one.   \n\n\n\nLine two.  \n== Section ==\nBody.   "
    assert clean_sections(text) == [
        Section(heading="", text="Line one.\n\nLine two."),
        Section(heading="Section", text="Body."),
    ]

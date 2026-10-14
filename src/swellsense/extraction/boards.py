from swellsense.llm import extract

from .schemas import BoardListing, BoardSpec
from .units import parse_dimension

INSTRUCTIONS = (
    "Extract surfboard specs from the listing. "
    "Copy dimensions exactly as written. Do not convert units or do any maths."
)


def extract_board(text: str) -> BoardSpec:
    listing = extract(text, BoardListing, INSTRUCTIONS)
    return BoardSpec(
        length_in=parse_dimension(listing.length),
        width_in=parse_dimension(listing.width),
        thickness_in=parse_dimension(listing.thickness),
        volume_l=listing.volume_l,
        tail=listing.tail,
        fins=listing.fins,
        board_type=listing.board_type,
    )

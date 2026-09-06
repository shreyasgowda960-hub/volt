"""Shared test helpers.

Exists because spec 017 stopped POST /drivers/register from auto-verifying.
Every test that registers a driver and then expects it to work now has to get
it approved first, and doing that through the REAL admin endpoint rather than
by writing the column keeps those tests honest: if the approval path breaks,
they break with it.

The spec's rule is "do not auto-approve anything, including in tests". This
respects it — there is no shortcut here, only the same two HTTP calls a human
reviewer would make.
"""

from httpx import AsyncClient

# Matches the ADMIN_REVIEW_TOKEN set by the autouse fixture in conftest.
ADMIN_HEADERS = {"X-Admin-Token": "test-admin-token"}


async def approve_driver_via_admin(client: AsyncClient, driver_id: int) -> None:
    """Approve a driver the way the owner would.

    Note this does NOT require documents to exist. That is a property of the
    approve endpoint, not a shortcut taken here: approval is a human act on a
    person, and a reviewer who has seen a licence in another channel can
    approve without one in the system. Whether that should be tightened is a
    product question — it is flagged in the spec 017 report rather than
    decided quietly in a test helper.
    """
    response = await client.post(
        f"/api/v1/admin/drivers/{driver_id}/approve",
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200, (
        f"approving driver {driver_id} failed: "
        f"{response.status_code} {response.text}"
    )


# Minimal valid files for upload tests. Real magic bytes, because the upload
# path sniffs the actual content and ignores the declared type — a fixture
# made of b"fake" would be rejected for the right reason and prove nothing.
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF_BYTES = b"%PDF-1.7\n" + b"\x00" * 64

# Announced as a JPEG, actually not one. This is the whole point of sniffing:
# the declared content type on a multipart part is caller-controlled.
NOT_AN_IMAGE = b"MZ\x90\x00" + b"\x00" * 64

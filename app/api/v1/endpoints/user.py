from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from app.models.trip import TowingTrip, TripReview
from app.schemas.trip import TripReviewCreate
from app.schemas.response import APIResponse
from app.api.deps import get_session, get_current_user
from app.models.driver import Driver


router = APIRouter()

@router.post("/user/trip/{trip_id}/rate", response_model=APIResponse)
async def submit_trip_rating(
    trip_id: str,
    payload: TripReviewCreate,
    session: AsyncSession = Depends(get_session),
    current_user = Depends(get_current_user)
) -> APIResponse:
    """
    Submits a 1-5 star rating for a completed trip, saves the categorical 
    feedback, and updates the driver's global average rating.
    """
    # 1. Fetch the trip and ensure it belongs to the user
    trip = await session.get(TowingTrip, trip_id) # Replace TowingTrip with your main Trip model
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")
        
    if str(trip.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized to rate this trip.")
        
    # Optional: Ensure the trip is actually completed before rating
    # if trip.status != TowingStatus.COMPLETED:
    #     raise HTTPException(status_code=400, detail="Can only rate completed trips.")

    if not trip.driver_id:
        raise HTTPException(status_code=400, detail="No driver was assigned to this trip.")

    # 2. Check if a review already exists for this trip
    existing_review = await session.execute(
        select(TripReview).where(TripReview.trip_id == trip.id)
    )
    if existing_review.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="This trip has already been rated.")

    # 3. Create the review record
    new_review = TripReview(
        trip_id=trip.id,
        driver_id=trip.driver_id,
        user_id=current_user.id,
        rating=payload.rating,
        categories=[cat.value for cat in payload.categories],
        comment=payload.comment
    )
    session.add(new_review)

    # 4. Fetch the Driver to update their aggregate rating
    driver = await session.get(Driver, trip.driver_id) # Replace Driver with your actual driver model
    if driver:
        # Mathematical recalculation of the rolling average
        current_total_score = driver.average_rating * driver.total_reviews
        driver.total_reviews += 1
        driver.average_rating = (current_total_score + payload.rating) / driver.total_reviews
        
        session.add(driver)

    # 5. Commit both the review and the driver update as a single transaction
    await session.commit()

    return APIResponse(
        success=True,
        message="Thank you for your feedback!",
        data={"review_id": str(new_review.id), "new_average_rating": round(driver.average_rating, 2)}
    )
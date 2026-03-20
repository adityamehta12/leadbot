"""Stripe billing integration.

Handles checkout session creation, webhook processing, and billing portal.
Gracefully degrades if stripe package is not installed.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.business import Business

logger = logging.getLogger(__name__)

try:
    import stripe

    _stripe_available = True
except ImportError:
    stripe = None  # type: ignore
    _stripe_available = False


def _ensure_stripe(api_key: str):
    """Verify that stripe is available and configured."""
    if not _stripe_available:
        raise RuntimeError("Stripe library is not installed. Run: pip install stripe")
    if not api_key:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    stripe.api_key = api_key


async def create_checkout_session(
    db: AsyncSession,
    business: Business,
    price_id: str,
    stripe_secret_key: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Create a Stripe Checkout session and return the URL."""
    _ensure_stripe(stripe_secret_key)

    # Create or retrieve Stripe customer
    if not business.stripe_customer_id:
        customer = stripe.Customer.create(
            metadata={"business_id": str(business.id), "slug": business.slug},
            name=business.name,
        )
        business.stripe_customer_id = customer.id
        await db.commit()
    else:
        customer = stripe.Customer.retrieve(business.stripe_customer_id)

    session = stripe.checkout.Session.create(
        customer=business.stripe_customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"business_id": str(business.id)},
    )

    return session.url


async def handle_webhook_event(
    db: AsyncSession,
    payload: bytes,
    sig_header: str,
    webhook_secret: str,
    stripe_secret_key: str,
):
    """Process a Stripe webhook event."""
    _ensure_stripe(stripe_secret_key)

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except stripe.error.SignatureVerificationError:
        raise ValueError("Invalid webhook signature")

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")
        business_id = data.get("metadata", {}).get("business_id")

        if business_id:
            result = await db.execute(
                select(Business).where(Business.id == uuid.UUID(business_id))
            )
        elif customer_id:
            result = await db.execute(
                select(Business).where(Business.stripe_customer_id == customer_id)
            )
        else:
            logger.warning("Checkout completed but no business_id or customer_id found")
            return

        business = result.scalar_one_or_none()
        if business:
            business.plan = "pro"
            business.stripe_subscription_id = subscription_id
            if customer_id and not business.stripe_customer_id:
                business.stripe_customer_id = customer_id
            await db.commit()
            logger.info("Business %s upgraded to pro plan", business.slug)

    elif event_type in ("customer.subscription.deleted", "customer.subscription.canceled"):
        customer_id = data.get("customer")
        if customer_id:
            result = await db.execute(
                select(Business).where(Business.stripe_customer_id == customer_id)
            )
            business = result.scalar_one_or_none()
            if business:
                business.plan = "free"
                business.stripe_subscription_id = None
                await db.commit()
                logger.info("Business %s downgraded to free plan", business.slug)

    elif event_type == "invoice.payment_failed":
        customer_id = data.get("customer")
        logger.warning("Payment failed for customer %s", customer_id)

    return event_type


async def create_portal_session(
    business: Business,
    stripe_secret_key: str,
    return_url: str,
) -> str:
    """Create a Stripe billing portal session and return the URL."""
    _ensure_stripe(stripe_secret_key)

    if not business.stripe_customer_id:
        raise ValueError("Business has no Stripe customer ID. Subscribe first.")

    session = stripe.billing_portal.Session.create(
        customer=business.stripe_customer_id,
        return_url=return_url,
    )

    return session.url

Epic: Order management modernization

User Story: Create order
As a sales user, I want to create an order so that fulfillment can begin.

Acceptance Criteria:
AC1: Required fields order date, customer, and at least one line item must be present.
AC2: Invalid product codes must be rejected.
AC3: Tax should be calculated for taxable products.
AC4: Order creation event must be available to downstream integrations.

User Story: Update order status
As an operations user, I want to update an order status so that downstream teams know the current state.

Acceptance Criteria:
AC1: Only valid state transitions are allowed.
AC2: Cancelled orders cannot move to shipped.
AC3: Status updates must be visible in reporting and notifications.

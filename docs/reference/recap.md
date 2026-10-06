## 1. Automatic approval routing

The system determines the required approver using **whichever requires higher authority: the requisition’s amount or the requester’s position**.

### Our final authority matrix

| Person raising the requisition | ₦1–₦5 million | Above ₦5 million–₦100 million | Above ₦100 million–₦500 million | Above ₦500 million |
|---|---|---|---|---|
| **Staff member, excluding the officeholders below** | Their department’s HOD | Chief of Staff | Managing Director | Board |
| **HOD** | Chief of Staff | Chief of Staff | Managing Director | Board |
| **Chief of Staff** | Managing Director | Managing Director | Managing Director | Board |
| **Managing Director** | Board | Board | Board | Board |

The upper limits are inclusive. **Exactly ₦5 million belongs to the HOD amount band, exactly ₦100 million to the Chief of Staff band, and exactly ₦500 million to the MD band**, unless the requester’s position requires escalation. :chatgpt-content-reference{index="0"}

### How routing works

**Routing is direct, not sequential.** A staff member’s ₦200 million requisition goes directly to the MD. It does not first require HOD or Chief of Staff approval.

For HOD-level requests, the system identifies the **HOD of the requester’s own department** from the official staff and department records. Above that level, the requesting department does not change the required authority.

**Self-request escalation must never lower an amount-based requirement.** For example, an HOD’s ₦3 million request goes to the Chief of Staff, but their ₦200 million request goes to the MD, and their ₦600 million request goes to the Board.

Nobody can approve their own request by switching roles or using another account linked to the same person. Likewise, a senior officer does not automatically gain permission to replace the assigned approver. Missing or conflicting assignments must block the affected action rather than trigger an invented substitute. :chatgpt-content-reference{index="1"}

The assigned individual approver can **approve, reject, or return the requisition for correction**. Returned requests require a new revision, fresh signing, and recalculated routing when resubmitted.

## 2. Board approval workflow

We selected **Board meeting resolutions for the first release**. Online Board voting and written-resolution circulation are deferred.

The workflow is:

**Awaiting Board Resolution → Company Secretary Records and Submits → Awaiting Chairman Sign-off → Board Outcome Recorded**

### Company Secretary: the recorder

After the Board meeting, the Secretary records the relevant company/Board, meeting date, resolution reference, actual decision, authorised amount, and any conditions. They attach the authenticated resolution or relevant minutes extract and link it to the **exact requisition version considered**.

The Secretary then signs and submits that record to the Chairman. **Recording or uploading the resolution alone does not approve the requisition.**

### Board Chairman: the final in-system approver

The Chairman reviews the request, the Secretary’s record, and the supporting resolution. They either **confirm and sign off** or **return the record to the Secretary for correction**, with a reason.

The Secretary and Chairman must be **two different individuals**. The Chairman cannot silently edit the Secretary’s submitted record, and corrections require renewed sign-off. :chatgpt-content-reference{index="2"}

### The system preserves the Board’s actual decision

**Chairman sign-off confirms the formal meeting decision; it does not replace the Board meeting or allow the Chairman to substitute a different decision.**

If the Board approved the request, confirmation finalises that approval. If the Board rejected or deferred it, confirmation preserves that outcome. An approval subject to conditions remains clearly conditional—it must not appear as unconditional approval. Returning the Secretary’s record for correction is also different from rejecting the expenditure. :chatgpt-content-reference{index="3"}

## 3. Controls applying to both workflows

**Every signature and decision must be tied to the exact request or resolution version.** Material changes cannot silently retain an earlier approval. The history must preserve who acted, what they signed, when they acted, and the supporting evidence, without allowing application users to rewrite it. :chatgpt-content-reference{index="4"} :chatgpt-content-reference{index="5"} :chatgpt-content-reference{index="6"}

We have **not defined an alternative approver when the Chairman is the requester, the same person occupies both Board roles, or an officeholder is unavailable**. Those cases must remain blocked until BNH authorises an arrangement—not bypassed automatically. :chatgpt-content-reference{index="7"}

Finally, **Accounts Verification, CAO/Admin, and Finance/Payment are excluded from this approval path. “Approved” means authorised—not paid.**
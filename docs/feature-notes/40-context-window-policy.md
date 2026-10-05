# Context-window policy

`allow_extended_context` is a shared preset/user policy field. It defaults to false, can be overridden for an individual user, and is included in the policy override list. The migration explicitly enables it for the existing user named `Devasheesh` and leaves all other users disabled.

The Claude proxy stores this policy alongside the other model controls so both proxy dashboards and account policies remain consistent. Provider context capabilities remain negotiated by the upstream Claude endpoint.

Explicitly selecting a user override persists that choice even when the value matches the preset. Only clearing the override restores inheritance. Devasheesh's protected extended-context setting remains enabled and marked as an override when he has a preset.

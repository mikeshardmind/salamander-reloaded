# reminders

settings-timezone-command = /settings timezone

reminder-embed-title = Your requested reminder
reminder-jump-label = Jump to around where you created this reminder
reminder-group = remindme
    .description = Remind yourself about something, later

remind-in-command = in
    .description = Set a reminder for an amount of time in the future
remind-at-command = at
    .description = Set a reminder for a specific time in the future
reminder-list-command = list
    .description = Show your upcoming reminders and optionally remove any of them

reminder-invalid-datetime = That isn't a date and time that can actually occur.
reminder-past-datetime = That time is in the past. (Not scheduling reminder)
reminder-schedule-confirm = Reminder scheduled at { $discord_formatted_time }
reminder-utc-footer = This was scheduled using UTC time, if this is not how you want to use this, please set your time using { settings-timezone-command }

# dice

dice-group = dice
    .description = Keep on rolling

dice-roll-command = roll
    .description = Roll some dice

dice-too-many-err = Oops, too many dice. I dropped them.
dice-too-many-kept-err = You can't keep more dice than you rolled.
dice-parse-expect-operator = Expected an operator next (Current: { $current })
dice-parse-expect-number-dice = Expected a number or die next (Current: { $current })
dice-parse-incomplete-expression = That's not a complete expression.

dice-info-command = info
    .description = Get info about an expression

dice-info-output = Information about dice Expression:
    expected value: { $ev }
    low: { $low }
    high: { $high }


# info tools

avatar-ctx = Avatar
raw-content-ctx = Raw content
no-content = No content.
raw-content-attached = Attached long raw content

"""Pre-built life events catalog — the stories that happen to agents."""

from hive.world.events import Choice, ConditionalFollowUp, LifeEvent, StatEffect

EVENTS: list[LifeEvent] = [
    LifeEvent(
        event_id="rent_increase",
        name="Landlord Raises Rent",
        description="Your landlord just announced a rent increase.",
        category="financial",
        min_cycles_alive=5,
        choices=[
            Choice(
                id="negotiate",
                description="Negotiate with the landlord",
                stat_effects=[StatEffect(stat="money", change=-50)],
                follow_up_events=[
                    ConditionalFollowUp(
                        event_id="negotiation_failed", probability=0.4, delay_cycles=2
                    ),
                ],
            ),
            Choice(
                id="pay",
                description="Pay the increase",
                stat_effects=[
                    StatEffect(stat="money", change=-200),
                    StatEffect(stat="happiness", change=-5, change_type="percent"),
                ],
            ),
            Choice(
                id="move",
                description="Move to a cheaper place",
                stat_effects=[
                    StatEffect(stat="money", change=-500),
                    StatEffect(stat="happiness", change=-10, change_type="percent"),
                ],
                follow_up_events=[
                    ConditionalFollowUp(
                        event_id="found_cheaper_place", probability=0.6, delay_cycles=3
                    ),
                ],
            ),
        ],
    ),
    LifeEvent(
        event_id="negotiation_failed",
        name="Negotiation Failed",
        description="The landlord rejected your negotiation. Pay up or move.",
        category="financial",
        choices=[
            Choice(
                id="pay_now",
                description="Pay the full increase",
                stat_effects=[StatEffect(stat="money", change=-200)],
            ),
            Choice(
                id="move_now",
                description="Move out immediately",
                stat_effects=[
                    StatEffect(stat="money", change=-300),
                    StatEffect(stat="energy", change=-0.2),
                ],
            ),
        ],
    ),
    LifeEvent(
        event_id="found_cheaper_place",
        name="Found a Cheaper Place",
        description="Your new neighborhood has lower costs. You're saving money.",
        category="financial",
        choices=[
            Choice(
                id="settle_in",
                description="Settle in and enjoy the savings",
                stat_effects=[
                    StatEffect(stat="money", change=100),
                    StatEffect(stat="happiness", change=10, change_type="percent"),
                ],
            ),
        ],
    ),
    LifeEvent(
        event_id="job_offer",
        name="Job Offer from Competitor",
        description="A rival company wants to hire you at a higher salary.",
        category="career",
        prerequisites={"reputation": 0.5},
        min_cycles_alive=10,
        choices=[
            Choice(
                id="accept",
                description="Accept the new job",
                stat_effects=[
                    StatEffect(stat="money", change=200),
                    StatEffect(stat="happiness", change=10, change_type="percent"),
                ],
                follow_up_events=[
                    ConditionalFollowUp(
                        event_id="old_boss_grudge", probability=0.3, delay_cycles=5
                    ),
                ],
            ),
            Choice(
                id="negotiate_raise",
                description="Decline but negotiate a raise at current job",
                stat_effects=[StatEffect(stat="money", change=100)],
            ),
            Choice(
                id="decline",
                description="Politely decline",
                stat_effects=[StatEffect(stat="reputation", change=0.05)],
            ),
        ],
    ),
    LifeEvent(
        event_id="old_boss_grudge",
        name="Old Boss Badmouths You",
        description="Your former employer is spreading negative things about you.",
        category="social",
        choices=[
            Choice(
                id="confront",
                description="Confront them directly",
                stat_effects=[
                    StatEffect(stat="reputation", change=-0.05),
                    StatEffect(stat="energy", change=-0.1),
                ],
            ),
            Choice(
                id="ignore",
                description="Ignore it and let your work speak",
                stat_effects=[StatEffect(stat="reputation", change=-0.1)],
                follow_up_events=[
                    ConditionalFollowUp(
                        event_id="reputation_recovers", probability=0.7, delay_cycles=8
                    ),
                ],
            ),
        ],
    ),
    LifeEvent(
        event_id="reputation_recovers",
        name="Reputation Recovered",
        description="People see through the gossip. Your reputation is restored.",
        category="social",
        choices=[
            Choice(
                id="grateful",
                description="Feel grateful and move on",
                stat_effects=[
                    StatEffect(stat="reputation", change=0.15),
                    StatEffect(stat="happiness", change=10, change_type="percent"),
                ],
            ),
        ],
    ),
    LifeEvent(
        event_id="health_scare",
        name="Health Scare",
        description="You've been feeling unwell. Something might be wrong.",
        category="health",
        min_cycles_alive=8,
        choices=[
            Choice(
                id="doctor",
                description="Go to the doctor",
                stat_effects=[
                    StatEffect(stat="money", change=-300),
                    StatEffect(stat="health", change=0.2),
                ],
            ),
            Choice(
                id="ignore",
                description="Ignore it and hope it passes",
                stat_effects=[],
                follow_up_events=[
                    ConditionalFollowUp(
                        event_id="condition_worsens", probability=0.5, delay_cycles=4
                    ),
                ],
            ),
            Choice(
                id="home_remedy",
                description="Try home remedies",
                stat_effects=[
                    StatEffect(stat="money", change=-50),
                    StatEffect(stat="health", change=0.05),
                ],
            ),
        ],
    ),
    LifeEvent(
        event_id="condition_worsens",
        name="Condition Worsens",
        description="Your health has deteriorated significantly.",
        category="health",
        choices=[
            Choice(
                id="emergency",
                description="Rush to emergency room",
                stat_effects=[
                    StatEffect(stat="money", change=-500),
                    StatEffect(stat="health", change=0.15),
                    StatEffect(stat="energy", change=-0.3),
                ],
            ),
            Choice(
                id="endure",
                description="Try to endure",
                stat_effects=[
                    StatEffect(stat="health", change=-0.3),
                    StatEffect(stat="happiness", change=-20, change_type="percent"),
                ],
            ),
        ],
    ),
    LifeEvent(
        event_id="friend_money",
        name="Friend Asks for Money",
        description="A close friend needs financial help urgently.",
        category="social",
        min_cycles_alive=5,
        choices=[
            Choice(
                id="lend",
                description="Lend them the money",
                stat_effects=[
                    StatEffect(stat="money", change=-200),
                    StatEffect(stat="reputation", change=0.1),
                ],
                follow_up_events=[
                    ConditionalFollowUp(
                        event_id="friend_pays_back", probability=0.6, delay_cycles=6
                    ),
                    ConditionalFollowUp(event_id="friend_ghosts", probability=0.4, delay_cycles=6),
                ],
            ),
            Choice(
                id="refuse",
                description="Refuse politely",
                stat_effects=[StatEffect(stat="reputation", change=-0.05)],
            ),
            Choice(
                id="help_other_way",
                description="Help them find a job instead",
                stat_effects=[
                    StatEffect(stat="reputation", change=0.05),
                    StatEffect(stat="energy", change=-0.15),
                ],
            ),
        ],
    ),
    LifeEvent(
        event_id="friend_pays_back",
        name="Friend Pays Back with Interest",
        description="Your friend returned the money plus extra as thanks.",
        category="social",
        choices=[
            Choice(
                id="accept",
                description="Accept gratefully",
                stat_effects=[
                    StatEffect(stat="money", change=250),
                    StatEffect(stat="happiness", change=10, change_type="percent"),
                ],
            ),
        ],
    ),
    LifeEvent(
        event_id="friend_ghosts",
        name="Friend Disappears",
        description="Your friend vanished with the money. They won't return calls.",
        category="social",
        choices=[
            Choice(
                id="write_off",
                description="Write it off as a loss",
                stat_effects=[
                    StatEffect(stat="happiness", change=-15, change_type="percent"),
                ],
            ),
            Choice(
                id="pursue",
                description="Try to track them down",
                stat_effects=[
                    StatEffect(stat="energy", change=-0.2),
                    StatEffect(stat="reputation", change=-0.05),
                ],
            ),
        ],
    ),
    LifeEvent(
        event_id="gambling_opportunity",
        name="Gambling Opportunity",
        description="Someone invites you to a high-stakes game.",
        category="financial",
        min_cycles_alive=3,
        choices=[
            Choice(
                id="bet_big",
                description="Go all in (high risk, high reward)",
                stat_effects=[StatEffect(stat="money", change=500)],
                follow_up_events=[
                    ConditionalFollowUp(event_id="big_loss", probability=0.7, delay_cycles=1),
                ],
            ),
            Choice(
                id="bet_small",
                description="Play it safe with a small bet",
                stat_effects=[StatEffect(stat="money", change=100)],
                follow_up_events=[
                    ConditionalFollowUp(event_id="small_loss", probability=0.5, delay_cycles=1),
                ],
            ),
            Choice(
                id="walk_away",
                description="Walk away",
                stat_effects=[StatEffect(stat="happiness", change=5, change_type="percent")],
            ),
        ],
    ),
    LifeEvent(
        event_id="big_loss",
        name="Big Gambling Loss",
        description="You lost big at the table.",
        category="financial",
        choices=[
            Choice(
                id="accept_loss",
                description="Accept the loss and move on",
                stat_effects=[
                    StatEffect(stat="money", change=-1000),
                    StatEffect(stat="happiness", change=-25, change_type="percent"),
                ],
                stressor="financial_strain",
                stressor_severity=0.4,
            ),
        ],
    ),
    LifeEvent(
        event_id="small_loss",
        name="Small Gambling Loss",
        description="You lost your small bet.",
        category="financial",
        choices=[
            Choice(
                id="accept",
                description="Shrug it off",
                stat_effects=[StatEffect(stat="money", change=-200)],
            ),
        ],
    ),
    LifeEvent(
        event_id="skill_workshop",
        name="Skill Workshop Available",
        description="An intensive workshop is running for a skill you could learn.",
        category="career",
        min_cycles_alive=5,
        choices=[
            Choice(
                id="attend",
                description="Attend the workshop (costs money but big skill boost)",
                stat_effects=[
                    StatEffect(stat="money", change=-300),
                    StatEffect(stat="energy", change=-0.2),
                ],
            ),
            Choice(
                id="skip",
                description="Skip it",
                stat_effects=[],
                follow_up_events=[
                    ConditionalFollowUp(
                        event_id="missed_promotion", probability=0.2, delay_cycles=5
                    ),
                ],
            ),
        ],
    ),
    LifeEvent(
        event_id="missed_promotion",
        name="Missed Promotion",
        description="A coworker who attended the workshop got promoted over you.",
        category="career",
        choices=[
            Choice(
                id="accept",
                description="Accept and work harder",
                stat_effects=[
                    StatEffect(stat="happiness", change=-10, change_type="percent"),
                    StatEffect(stat="energy", change=-0.1),
                ],
            ),
        ],
    ),
    LifeEvent(
        event_id="windfall",
        name="Unexpected Windfall",
        description="You found money you forgot you had in an old account.",
        category="financial",
        min_cycles_alive=15,
        choices=[
            Choice(
                id="save",
                description="Save it",
                stat_effects=[
                    StatEffect(stat="money", change=300),
                    StatEffect(stat="happiness", change=5, change_type="percent"),
                ],
                resolves_stressor="financial_strain",
            ),
            Choice(
                id="treat_yourself",
                description="Treat yourself",
                stat_effects=[
                    StatEffect(stat="money", change=100),
                    StatEffect(stat="happiness", change=15, change_type="percent"),
                ],
            ),
        ],
    ),
    LifeEvent(
        event_id="burnout",
        name="Burnout Warning",
        description="You've been working too hard. Your energy is crashing.",
        category="health",
        prerequisites={"energy": -0.3},
        min_cycles_alive=10,
        choices=[
            Choice(
                id="rest",
                description="Take a break",
                stat_effects=[
                    StatEffect(stat="energy", change=0.4),
                    StatEffect(stat="happiness", change=10, change_type="percent"),
                    StatEffect(stat="money", change=-100),
                ],
                resolves_stressor="burnout",
            ),
            Choice(
                id="push_through",
                description="Push through it",
                stat_effects=[
                    StatEffect(stat="energy", change=-0.2),
                    StatEffect(stat="health", change=-0.1),
                ],
                stressor="burnout",
                stressor_severity=0.35,
            ),
        ],
    ),
]

EVENT_MAP: dict[str, LifeEvent] = {e.event_id: e for e in EVENTS}

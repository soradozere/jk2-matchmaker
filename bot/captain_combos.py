# -*- coding: utf-8 -*-
""" Pre-agreed captain pairings for the "captain combos" pick_captains mode.
	Sourced from the community's own list (Captain Combos.txt, 4 Sept 2026).
	To update: send an updated file and this gets redeployed -- there's no
	in-Discord editor for it yet.

	Matched against each player's SORACLE NAME (their site profile name), not
	whatever their Discord nickname happens to be -- that's the identity the
	list was written against.

	perfect=True pairs are used whenever both players are in the same queue.
	perfect=False ("Conditional") pairs are a fallback, used only when no
	perfect pair is available in that queue -- per the source list, these
	should be rare. first_pick names who gets first pick for a conditional
	pair; a perfect pair's first pick is random between the two. """

import random

COMBOS = [
	# name_a, name_b, perfect, first_pick (None unless conditional)
	("Bizzle", "Fetchd", True, None),
	("Bizzle", "Cooky", True, None),
	("Bizzle", "Ultra", True, None),
	("Bizzle", "Interlude", False, "Interlude"),
	("Bizzle", "Cheese", False, "Cheese"),
	("Bizzle", "Arhont", False, "Arhont"),

	("Fetchd", "Cooky", True, None),
	("Fetchd", "Ultra", True, None),
	("Fetchd", "Interlude", False, "Interlude"),
	("Fetchd", "Cheese", False, "Cheese"),
	("Fetchd", "Arhont", False, "Arhont"),

	("Cooky", "Ultra", True, None),
	("Cooky", "Interlude", True, None),
	("Cooky", "Cheese", False, "Cheese"),
	("Cooky", "Arhont", False, "Arhont"),
	("Cooky", "Shax", False, "Shax"),

	("Interlude", "Ultra", True, None),
	("Interlude", "Original", True, None),
	("Interlude", "Shax", True, None),
	("Interlude", "Twinblade", False, "Twinblade"),
	("Interlude", "Cheese", False, "Cheese"),

	("Original", "Cooky", True, None),
	("Original", "Shax", True, None),
	("Original", "Twinblade", True, None),
	("Original", "Suvix", False, "Suvix"),

	("Cheese", "Arhont", True, None),
	("Cheese", "Ultra", True, None),
	("Cheese", "Andrew", False, "Andrew"),

	("Suvix", "Twinblade", True, None),
	("Suvix", "Retpecs", True, None),
	("Suvix", "Shax", True, None),
	("Suvix", "Jin", True, None),

	("Shax", "Twinblade", True, None),
	("Shax", "Retpecs", True, None),

	("Twinblade", "Andrew", True, None),
	("Twinblade", "Jin", True, None),
	("Twinblade", "Retpecs", True, None),

	("Arhont", "Andrew", True, None),
	("Arhont", "Ultra", True, None),

	("Retpecs", "Jin", True, None),

	("Jin", "Glempa", True, None),
	("Jin", "Phoenix", True, None),
	("Jin", "Andrew", True, None),
	("Jin", "Xan", True, None),
	("Jin", "Eze", False, "Eze"),

	("Phoenix", "Glempa", True, None),
	("Phoenix", "Xan", True, None),

	("Glempa", "Xan", True, None),
	("Glempa", "Luke", True, None),

	("Canon", "Giraffe", True, None),
	("Canon", "Flawless", True, None),
	("Canon", "Eze", True, None),
	("Canon", "Levi", True, None),
	("Canon", "Yuki", True, None),

	("Xan", "Luke", True, None),
	("Xan", "Yuki", True, None),
	("Xan", "Millhouse", True, None),
	("Xan", "Downfall", False, "Downfall"),

	("Eze", "Flawless", True, None),
	("Eze", "Yuki", True, None),
	("Eze", "Levi", True, None),
	("Eze", "Giraffe", True, None),

	("Giraffe", "Levi", True, None),
	("Giraffe", "Flawless", True, None),
	("Giraffe", "Yuki", True, None),

	("Millhouse", "Downfall", True, None),

	("Flawless", "Levi", True, None),
	("Flawless", "Yuki", True, None),

	("Levi", "Yuki", True, None),

	("Sora", "Downfall", True, None),
	("Sora", "Slimm", True, None),

	("Storm", "Riji", True, None),
	("Downfall", "Slimm", True, None),

	("Sora", "Devy", False, "Devy"),
]


def _norm(name):
	return (name or "").strip().lower()


def pick_pair(pool_names):
	""" pool_names: dict(discord_id -> soracle name) for everyone eligible to
		captain in the current queue.

		Returns [first_pick_id, second_pick_id], or None if nothing in COMBOS
		matches two different people currently in the pool. Perfect Match pairs
		are tried first; Conditional pairs are only considered if no Perfect
		Match is available, per the source list. A tie among several equally-
		eligible pairs breaks randomly. """
	by_name = {_norm(name): pid for pid, name in pool_names.items()}

	def matches(want_perfect):
		found = []
		for name_a, name_b, perfect, first_pick in COMBOS:
			if perfect != want_perfect:
				continue
			pid_a, pid_b = by_name.get(_norm(name_a)), by_name.get(_norm(name_b))
			if pid_a is not None and pid_b is not None and pid_a != pid_b:
				found.append((pid_a, pid_b, first_pick))
		return found

	candidates = matches(True) or matches(False)
	if not candidates:
		return None

	pid_a, pid_b, first_pick = random.choice(candidates)
	if first_pick is None:
		return random.sample([pid_a, pid_b], 2)

	first_id = pid_a if _norm(first_pick) == _norm(pool_names[pid_a]) else pid_b
	return [first_id, pid_b if first_id == pid_a else pid_a]

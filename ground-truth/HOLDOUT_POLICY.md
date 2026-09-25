# Sequestered Profile B v2 holdout policy

The historical exposed 80-query TEST set is a qualification/regression set.
It must not be represented as a hidden final holdout.

A final holdout is authored source-first by an independent authorized group,
sealed outside the development workspace, and consumed only after exact MESA,
MESA_Data, E2E, config, scorer, prompt, model, and threshold identities have
been frozen. Development agents receive no plaintext query, qrel, required
fact, expected answer, or gold evidence identifier.

The public repository may contain only a validated manifest with:

- a non-reversible manifest hash;
- class distribution;
- creation protocol;
- sealed storage reference;
- lifecycle status.

Holdout size and audit percentages are methodology decisions and must be
approved before release freeze. Failure on a consumed final holdout must not
trigger tuning against that same holdout.

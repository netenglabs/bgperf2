# Exact attribute grouping in the MRT injector

Selected 2026-11-09 after a small community control produced four observer
prefixes instead of one and the frozen injector reported one attribute path
for four source paths. This is apparatus diagnosis, not a daemon-policy result.

Upstream `a0191842fedf001abbda6364ab5c70d3f1c0788d` calls `ptree_search` in
`bgpdump_add_prefix` to reuse an attribute block. That function returns a
populated longest prefix match. A shorter attribute block can therefore absorb
a later block with trailing communities. Upstream already provides
`ptree_search_exact`, which requires equal key length. Preserve upstream
attribution and all original images/results.

Deliver an opt-in `<full-upstream-commit>-pa-exact-v1` build profile. Default
refs/recipes remain unpatched. Resolve only a full lowercase 40-hex source
commit for this profile. Guard the exact source statement before and after a
one-call substitution, fail on source drift, compile normally, and record the
explicit patch identity in the image and its queried version. Keep original
source revision, applied recipe, image ID and binary hash distinct. A profile
name does not prove a native binary or preserve attributes by itself.

Modeled checks must exercise patch application, refusal without the expected
statement, source/profile parsing, unchanged ordinary recipes and defensive
version parsing. Review and run the engine gate before building. Then use a new
image/tag and fresh native control identities to qualify the corrected injector;
retain failures and never reinterpret prior results. Full-table replay remains
unqualified until explicit expected sets and protocol controls pass.

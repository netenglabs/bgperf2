# Preserve unknown EVPN extended communities in the observer

Selected 2026-11-09 after a full-table BIRD original exported the expected
1,056,163 prefixes while sink 0.3.0 retained 1,056,162. The retained sink log
names treat-as-withdraw for unknown EVPN subtype 249. Exact source inspection
finds that subtype in the missing route's correctly sized extended-community
attribute. RFC 7606 section 7.14 forbids treating an unknown type/subtype as an
error. Preserve the failed original and unchanged source/expected set.

Prepare sink 0.4.0 with a narrowly source-bound GoBGP v4.9.0 parser correction:
replace only the unknown-EVPN fallback error with its existing opaque unknown
community constructor. Preserve all eight bytes, known subtype validation,
malformed-length handling, framing, session negotiation, clocks, count/table,
assurance and capture behavior. This deliberately differs from unpatched
GoBGP for this standards defect; do not claim universal GoBGP parity.

Verify the complete pinned dependency file hash and exact old statement, create
an exclusive private module copy, and never edit the module cache or downloaded
input. Apply the same maintained dependency-copy command in image builds and the Go
vet/race runner. Bind it in image recipe identity and report the explicit parser
profile in the binary banner. Retain old immutable images and use fresh originals.

Tests cover unknown subtype round-trip bytes, adjacent known communities,
malformed length/known errors, full-session accepted prefixes and strict patch
refusals. Run focused Python and pinned-toolchain Go vet/race checks, review,
then required engine checks before building. Native qualification requires a
committed small MRT control containing the same unknown extension before a
new full-table original. This is a new instrument identity, not retrospective
acceptance of the old calibration or permission to pool different instruments.

Reference: https://www.rfc-editor.org/rfc/rfc7606.html#section-7.14

Go forbids overlays of files inside GOMODCACHE. The maintained build therefore
copies the verified pinned module into a fresh private directory, checks the
copied source hash again, patches that copy, and uses a private `-modfile` with
one explicit local replacement. Original project go.mod/go.sum and cached
module bytes stay unchanged; copied attribution/license files remain intact.

The private modfile must retain the pinned original dependency declaration and
must not override an existing replacement. Go vet/tests/build use `-mod=readonly`
so native qualification does not silently revise the selected dependency graph.


Local review found no code blockers. Documentation duplication/wording followups
were corrected. The pinned native Go vet/race runner succeeded with all modules
verified, the guarded source hash matching, and the original cached file hash
unchanged afterward. This directly checks the dependency constants and value-copy
behavior that the read-only reviewer could not access in the external cache.
Image/banner verification and the small native MRT qualification remain separate.


The first candidate build refused at Dockerfile parsing before compilation:
a literal newline in the generated shell argument exposed `replace` as a Docker
instruction. Generate the modfile separator with printf escapes instead, require
single-line build commands, and reject multiline/NUL paths. Modeled tests retain
the exact resulting modfile bytes and guard the Dockerfile context. The original
observer image remains unchanged. This renderer correction changes no Go parser
bytes; the pinned Go vet/race result remains applicable, and a fresh image build
must run its own Go vet/tests before qualification.

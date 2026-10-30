# Native relational KQL2 compiler implementation plan

> Use superpowers:executing-plans inline; one fresh final reviewer, no implementer delegates.

Goal: complete native relational checking/lowering from prepared KQL2 syntax.
Spec: ../specs/2026-10-29-rust-kql-relational-compiler-design.md.
Linux x86_64, Rust1.95, existing locked versions. Existing authorized branch in
place. No accepted baseline/model/CI replay; original1066 auth before/after fresh
observations, typed tags including QuotedTerm and ordered mappings retained.
User asks larger/fewer validations and independent implementation/push.

Review focus: literal/role alias identity and ordered map exports; branch-private
roles/types and absence witnesses; recursive/shared declaration cache/inlining;
error wrapping and malformed regex/AST; wide/deep/DAG materialization work.

1. [x] Capture fresh relational outputs/has_graph/errors from accepted prepared
   ASTs and new focused examples once; pinned vocabulary and tagged literal maps.
2. [x] Implement immutable typed plans, ordered maps, literal terms and compiler
   metadata; preserve IndexedProgram compatibility while sharing Program protocol.
3. [x] Complete source selector/check/comparison lowering and relational scopes,
   pattern cache/forward inlining; add explicit-snapshot coordinator if coherent.
4. [x] Group complete pinned parity and native resource/immutability/identity
   tests, strict Clippy/fmt; targeted reruns only for concrete failures.
5. [x] One fresh read-only final review, Important/Critical RED→GREEN in one pass,
   full affected suite, docs/justified memory and authorized commit/push.

Completed with39 affected native roots,440 relational+34 coordinator+127 new
regex observations, strict Clippy/fmt and one final review/repair pass. Regex
validation uses a bounded native grammar checker and frozen property vocabulary;
no added dependency. Current branch commit/push authorized; raw/workspace local.

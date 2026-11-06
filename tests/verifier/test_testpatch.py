"""Unit tests for the paths a hidden ``test.patch`` creates."""

from __future__ import annotations

from factory.verifier.testpatch import created_paths

MODIFY_ONLY = b"""diff --git a/tests/test_calc.py b/tests/test_calc.py
index d76a230..ffb53d4 100644
--- a/tests/test_calc.py
+++ b/tests/test_calc.py
@@ -39,3 +39,5 @@ def test_round_half_up_one_digit() -> None:
 
 def test_round_half_up_one_digit() -> None:
     assert round_half_up(1.24, 1) == 1.2
+
+def test_round_half_up_ties() -> None:
"""

CREATE = b"""diff --git a/tests/test_extra.py b/tests/test_extra.py
new file mode 100644
index 0000000..f639899
--- /dev/null
+++ b/tests/test_extra.py
@@ -0,0 +1,2 @@
+def test_extra() -> None:
+    assert True
"""

CREATE_SEVERAL = b"""diff --git a/tests/test_one.py b/tests/test_one.py
new file mode 100644
--- /dev/null
+++ b/tests/test_one.py
@@ -0,0 +1 @@
+x = 1
diff --git a/tests/pkg/test_two.py b/tests/pkg/test_two.py
new file mode 100755
--- /dev/null
+++ b/tests/pkg/test_two.py
@@ -0,0 +1 @@
+y = 2
diff --git a/tests/test_old.py b/tests/test_old.py
--- a/tests/test_old.py
+++ b/tests/test_old.py
@@ -1,1 +1,1 @@
-x = 1
+x = 2
"""

CREATE_BINARY = b"""diff --git a/tests/fixtures/blob.bin b/tests/fixtures/blob.bin
new file mode 100644
index 0000000..1111111
GIT binary patch
literal 5
Mc$_OibY^+W00000
"""


def test_a_normal_patch_creates_its_new_file() -> None:
    assert created_paths(CREATE) == frozenset({"tests/test_extra.py"})


def test_a_patch_that_only_modifies_creates_nothing() -> None:
    assert created_paths(MODIFY_ONLY) == frozenset()


def test_a_patch_that_creates_several_files_lists_them_all() -> None:
    assert created_paths(CREATE_SEVERAL) == frozenset(
        {"tests/test_one.py", "tests/pkg/test_two.py"}
    )


def test_a_binary_section_without_a_plus_header_is_still_detected() -> None:
    assert created_paths(CREATE_BINARY) == frozenset({"tests/fixtures/blob.bin"})


def test_an_empty_patch_creates_nothing() -> None:
    assert created_paths(b"") == frozenset()

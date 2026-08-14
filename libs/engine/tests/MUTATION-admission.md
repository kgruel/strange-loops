# Mutation Testing Report: `engine.admission`

- **Target Module**: `libs/engine/src/engine/admission.py`
- **Test Suite**: `libs/engine/tests/test_admission.py`
- **Total Mutants**: 21
- **Killed (initial)**: 13
- **Initial Survivors**: 8
- **Killed (final)**: 21
- **Final Survivors**: 0

## Initial Survivors & Resolutions

| # | Mutant ID & Location | Diff Summary | Class | Added Killing Test |
|---|----------------------|--------------|-------|--------------------|
| 1 | `engine.admission.xǁUnknownObserverǁ__init____mutmut_1`<br>`admission.py:44` | Replaces exception message formatting string with `None` in `super().__init__(...)` | `gap` | `TestAdmissionMutationCoverage.test_unknown_observer_exception_attributes_and_message` |
| 2 | `engine.admission.xǁUnknownObserverǁ__init____mutmut_3`<br>`admission.py:51` | `self.vertex = vertex` -> `self.vertex = None` | `gap` | `TestAdmissionMutationCoverage.test_unknown_observer_exception_attributes_and_message`<br>`TestGrantForObserver.test_unknown_observer_raises_typed` |
| 3 | `engine.admission.xǁUndeclaredKindǁ__init____mutmut_1`<br>`admission.py:63` | Replaces exception message formatting string with `None` in `super().__init__(...)` | `gap` | `TestAdmissionMutationCoverage.test_undeclared_kind_exception_attributes_and_message` |
| 4 | `engine.admission.xǁUndeclaredKindǁ__init____mutmut_3`<br>`admission.py:70` | `self.vertex = vertex` -> `self.vertex = None` | `gap` | `TestAdmissionMutationCoverage.test_undeclared_kind_exception_attributes_and_message` |
| 5 | `engine.admission.xǁAggregateAdmissionUnsupportedǁ__init____mutmut_1`<br>`admission.py:83` | Replaces exception message formatting string with `None` in `super().__init__(...)` | `gap` | `TestAdmissionMutationCoverage.test_aggregate_unsupported_exception_attributes_and_message` |
| 6 | `engine.admission.xǁAggregateAdmissionUnsupportedǁ__init____mutmut_2`<br>`admission.py:88` | `self.vertex = vertex` -> `self.vertex = None` | `gap` | `TestAdmissionMutationCoverage.test_aggregate_unsupported_exception_attributes_and_message`<br>`TestGrantForObserver.test_aggregate_vertex_refused` |
| 7 | `engine.admission.x_grant_for_observer__mutmut_4`<br>`admission.py:112` | `raise AggregateAdmissionUnsupported(ast.name)` -> `raise AggregateAdmissionUnsupported(None)` | `gap` | `TestAdmissionMutationCoverage.test_grant_for_observer_propagates_vertex_name_to_aggregate_exception`<br>`TestGrantForObserver.test_aggregate_vertex_refused`<br>`TestGrantForObserver.test_combine_aggregate_vertex_refused` |
| 8 | `engine.admission.x_grant_for_observer__mutmut_11`<br>`admission.py:125` | `raise UnknownObserver(observer, ast.name)` -> `raise UnknownObserver(observer, None)` | `gap` | `TestAdmissionMutationCoverage.test_grant_for_observer_propagates_vertex_name_to_unknown_observer_exception`<br>`TestGrantForObserver.test_unknown_observer_raises_typed` |

## Final Mutation Run

All 21 mutants in `engine.admission` are killed by the test suite (100% mutation kill rate, 0 surviving mutants).

SURVIVORS: 0 (all equivalent/finding)

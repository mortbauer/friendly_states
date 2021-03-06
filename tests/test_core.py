from __future__ import annotations

import functools
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from friendly_states.core import AttributeState, IncorrectInitialState, BaseState, MappingKeyState, extract_state_names
from friendly_states.exceptions import StateChangedElsewhere, IncorrectSummary, MultipleMachineAncestors, \
    InheritedFromState, CannotInferOutputState, DuplicateStateNames, DuplicateOutputStates, UnknownOutputState, \
    ReturnedInvalidState, GetStateDidNotReturnState


def my_deco(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        return f(*args, **kwargs)

    return wrapper


class TrafficLightMachine(AttributeState):
    is_machine = True

    class Summary:
        Green: [Yellow]
        Yellow: [Red]
        Red: [Green]


class Green(TrafficLightMachine):
    @my_deco
    def slow_down(self) -> [Yellow]:
        pass


class Yellow(TrafficLightMachine):
    def stop(self) -> [Red]:
        pass


class Red(TrafficLightMachine):
    def go(self) -> [Green]:
        pass


TrafficLightMachine.complete()


class StatefulThing:
    def __init__(self, state):
        self.state = state

    def __repr__(self):
        return f"{self.__class__.__name__}(state={self.state})"


class OtherMachine(AttributeState):
    is_machine = True


class State1(OtherMachine):
    def to_2(self) -> [State2]:
        self.set_state(State1, State2)  # this is wrong


class State2(OtherMachine):
    def to_1(self) -> [State1]:
        pass


OtherMachine.complete()


@contextmanager
def raises(exception_class, match=None, **kwargs):
    with pytest.raises(exception_class, match=match) as exc_info:
        yield
    exc = exc_info.value
    for key, value in kwargs.items():
        assert getattr(exc, key) == value


def test_transitions():
    light = StatefulThing(Green)
    assert light.state is Green
    Green(light).slow_down()
    assert light.state is Yellow
    Yellow(light).stop()
    assert light.state is Red
    Red(light).go()
    assert light.state is Green
    with raises(
            IncorrectInitialState,
            obj=light,
            desired=Red,
            state=Green,
            message='StatefulThing(state=Green) should be in state Red but is actually in state Green',
    ):
        Red(light)


def test_state_changed_elsewhere():
    obj = StatefulThing(State1)
    with raises(
            StateChangedElsewhere,
            obj=obj,
            state=State2,
            desired=State1,
            message="The state of StatefulThing(state=State2) has changed to State2 "
                    "since instantiating State1. "
                    "Did you change the state inside a transition method? Don't.",
    ):
        State1(obj).to_2()


def test_attributes():
    assert Green.slug == "Green"
    assert Green.label == "Green"
    assert Green.output_states == {Yellow}
    assert Green.slow_down.output_states == {Yellow}
    assert TrafficLightMachine.states == {Green, Yellow, Red}
    assert OtherMachine.states == {State1, State2}
    with pytest.raises(AttributeError):
        str(TrafficLightMachine.output_states)


def test_graph():
    class Graph:
        Green: [Yellow, Red]
        Yellow: [Red]
        Red: [Green]

    with raises(
            IncorrectSummary,
            message="""
Wrong outputs:

Outputs of Green:
According to summary       : Red, Yellow
According to actual classes: Yellow

"""):
        TrafficLightMachine.check_summary(Graph)


def test_repr():
    assert repr(BaseState) == "<class 'friendly_states.core.BaseState'>"
    assert repr(TrafficLightMachine) == "TrafficLightMachine"
    assert repr(Green) == "Green"
    assert repr(Green(StatefulThing(Green))) == "Green(obj=StatefulThing(state=Green))"


def test_abstract_classes():
    class MyMachine(MappingKeyState):
        is_machine = True

        class Summary:
            Loner: [Child1]
            Child1: [Loner, Child2]
            Child2: [Loner, Child1]

    class Loner(MyMachine):
        def to_child1(self) -> [Child1]:
            pass

    class Parent(MyMachine):
        is_abstract = True
        x = 9

        def to_loner(self) -> [Loner]:
            pass

        def foo(self) -> Loner:
            return Loner(None)

        def bar(self):
            pass

        def spam(self) -> []:
            pass

    class Mixin:
        pass

    class Child1(Mixin, Parent):
        x = 1

        def to_child2(self) -> [Child2]:
            pass

    class Child2(Parent):
        x = 2

        def to_child1(self) -> [Child1]:
            pass

    MyMachine.complete()

    thing = dict(state=Child1)
    assert Parent(thing).x == 1
    assert type(Parent(thing)) is Child1
    Child1(thing).to_child2()
    assert thing["state"] is Child2
    assert Parent(thing).x == 2
    assert type(Parent(thing)) is Child2
    Child2(thing).to_child1()
    assert thing["state"] is Child1
    Child1(thing).to_loner()
    assert thing["state"] is Loner

    with raises(IncorrectInitialState):
        Parent(thing)

    assert MyMachine.states == {Loner, Child1, Child2}
    assert Child1.machine is MyMachine
    assert Child1.direct_transitions == {Child1.to_child2}
    assert Child1.transitions == {Child1.to_child2, Parent.to_loner}


def test_multiple_machines():
    class Machine1(AttributeState):
        is_machine = True

    with raises(
            MultipleMachineAncestors,
            message=("Multiple machine classes found in ancestors of Machine2: "
                     "[Machine2, Machine1]")
    ):
        class Machine2(Machine1):
            is_machine = True

        str(Machine2)

    class Machine3(AttributeState):
        is_machine = True

    class Machine4(AttributeState):
        is_machine = True

    with raises(
            MultipleMachineAncestors,
            machine_classes=[Machine3, Machine4],
            message=("Multiple machine classes found in ancestors of State: "
                     "[Machine3, Machine4]"),
    ):
        class State(Machine3, Machine4):
            pass

        str(State)


def test_inherit_from_state():
    class MyMachine(AttributeState):
        is_machine = True

    class S1(MyMachine):
        pass

    with raises(
            InheritedFromState,
            ancestor=S1,
            machine=MyMachine,
            message=("S2 inherits from S1 and both are part of the machine MyMachine, but S1 is "
                     "not abstract. If it should be, mark it with is_abstract = True. You cannot "
                     "inherit from actual state classes."),
    ):
        class S2(S1):
            pass

        str(S2)


def test_complete_non_machine():
    with pytest.raises(ValueError):
        AttributeState.complete()


def test_multiple_output_states():
    class Machine(AttributeState):
        is_machine = True

        class Summary:
            S1: [S2, S3]
            S2: []
            S3: []

    class S1(Machine):
        def transit(self, out) -> [S2, S3]:
            if out == 1:
                return S2
            if out == 2:
                return S3
            if out == 4:
                return 3

    class S2(Machine):
        pass

    class S3(Machine):
        pass

    Machine.complete()

    thing = StatefulThing(S1)
    assert thing.state is S1
    S1(thing).transit(1)
    assert thing.state is S2

    thing = StatefulThing(S1)
    S1(thing).transit(2)
    assert thing.state is S3

    thing = StatefulThing(S1)
    with raises(
            CannotInferOutputState,
            output_states=[S2, S3],
            func=S1.transit.__wrapped__,
            match=r"This transition <function test_multiple_output_states.<locals>.S1.transit at 0x\w+> "
                  r"has multiple output states \[S2, S3\], you must return one.",
    ):
        S1(thing).transit(3)

    thing = StatefulThing(S1)
    with raises(
            ReturnedInvalidState,
            output_states=[S2, S3],
            func=S1.transit.__wrapped__,
            result=3,
            match=r"The transition <function test_multiple_output_states.<locals>.S1.transit at 0x\w+> "
                  r"returned 3, which is not in the declared output states \[S2, S3\]",
    ):
        S1(thing).transit(4)


def test_duplicate_state_names():
    class Machine(AttributeState):
        is_machine = True

    class S(Machine):
        pass

    s1 = S

    class S(Machine):
        pass

    s2 = S

    with raises(
            DuplicateStateNames,
            states={s1, s2},
            message="Some of the states frozenset({S, S}) in this machine have the same name.",
    ):
        Machine.complete()


def test_duplicate_output_states():
    class Machine(AttributeState):
        is_machine = True

    class S1(Machine):
        def transit(self, out) -> [S2, S2]:
            pass

    class S2(Machine):
        pass

    with raises(
            DuplicateOutputStates,
            func=S1.transit,
            cls=S1,
            output_names=["S2", "S2"],
            match=r"The transition function "
                  r"<function test_duplicate_output_states.<locals>.S1.transit at 0x\w+> "
                  r"in the class S1 declares some output states more than once: \['S2', 'S2'\]",
    ):
        Machine.complete()


def test_unknown_output_state():
    class Machine(AttributeState):
        is_machine = True

    class S1(Machine):
        def transit(self, out) -> [S2]:
            pass

    class S2:
        pass

    with raises(
            UnknownOutputState,
            func=S1.transit,
            cls=S1,
            name="S2",
            states={S1},
            match=r"The transition function "
                  r"<function test_unknown_output_state.<locals>.S1.transit at 0x\w+> "
                  r"in the class S1 declares an output state S2 "
                  r"which doesn't exist in the state machine. "
                  r"The available states are frozenset\(\{S1\}\). "
                  r"Did you forget to inherit from the machine\?",
    ):
        Machine.complete()


def test_generate_classes():
    class Machine(AttributeState):
        is_machine = True

        class Summary:
            S1: [S2, S3]
            S2: [S3]
            S3: []

    with raises(
            IncorrectSummary,
            message="""
Missing states:

class S1(Machine):
    def to_s_2(self) -> [S2]:
        pass

    def to_s_3(self) -> [S3]:
        pass


class S2(Machine):
    def to_s_3(self) -> [S3]:
        pass


class S3(Machine):
    pass


"""):
        Machine.complete()


def test_bad_get_state():
    class MyState(BaseState):
        def get_state(self):
            return 3

        def set_state(self, previous_state, new_state):
            pass

    class Machine(MyState):
        is_machine = True

    class State(Machine):
        pass

    Machine.complete()

    with raises(
            GetStateDidNotReturnState,
            returned=3,
            message="get_state is supposed to return a subclass of BaseState, "
                    "but it returned 3",
    ):
        State(None)


def test_slugs_and_labels():
    class Machine(AttributeState):
        is_machine = True

    class S1(Machine):
        slug = "AbcDef"

    class S2(Machine):
        slug = "AbcDef"
        label = "A Label"

    assert S1.slug == "AbcDef"
    assert S1.label == "Abc Def"

    assert S2.slug == "AbcDef"
    assert S2.label == "A Label"

    with raises(
            DuplicateStateNames,
            slug_to_state=[
                ("AbcDef", S1),
                ("AbcDef", S2),
            ],
            message="Some of the states in this machine have the same slug: "
                    "[('AbcDef', S1), ('AbcDef', S2)]",
    ):
        Machine.complete()


def test_already_complete():
    with raises(
            ValueError,
            match="This machine is already complete, you cannot add more subclasses.",
    ):
        class Purple(TrafficLightMachine):
            pass

        str(Purple)


def test_ensure_complete():
    class Machine(AttributeState):
        is_machine = True

    class S1(Machine):
        pass

    with pytest.raises(
            ValueError,
            match=r"This machine is not complete, call Machine.complete\(\) "
                  r"after declaring all states \(subclasses\)."
    ):
        S1(Machine)


def test_dynamic_attr_recipe():
    class DynamicAttributeState(AttributeState):
        def __init__(self, obj, attr_name):
            self.attr_name = attr_name
            super().__init__(obj)

    class Machine(DynamicAttributeState):
        is_machine = True

    class S1(Machine):
        def to_s2(self) -> [S2]:
            pass

    class S2(Machine):
        pass

    Machine.complete()

    thing = StatefulThing(S1)
    thing.other_state = S1

    assert thing.state is S1
    assert thing.other_state is S1

    S1(thing, "state").to_s2()
    assert thing.state is S2
    assert thing.other_state is S1

    S1(thing, "other_state").to_s2()
    assert thing.state is S2
    assert thing.other_state is S2


def machine_factory():
    class Machine(AttributeState):
        is_machine = True

    class CommonState1(Machine):
        def to_common_state_2(self) -> [CommonState2]:
            pass

    class CommonState2(Machine):
        pass

    return SimpleNamespace(
        Machine=Machine,
        CommonState1=CommonState1,
        CommonState2=CommonState2,
    )


def test_similar_machines_recipe():
    machine1 = machine_factory()

    class DifferentState(machine1.Machine):
        def to_common_state_2(self) -> [machine1.CommonState2]:
            pass

    str(DifferentState)

    machine1.Machine.complete()

    class Summary:
        CommonState1: [CommonState2]
        CommonState2: []
        DifferentState: [CommonState2]

    machine1.Machine.check_summary(Summary)

    machine2 = machine_factory()
    machine2.Machine.complete()

    class Summary:
        CommonState1: [CommonState2]
        CommonState2: []

    machine2.Machine.check_summary(Summary)


def test_extract_state_names():
    assert extract_state_names("x x") is None
    assert extract_state_names("") is None
    assert extract_state_names("x;x") is None
    assert extract_state_names("[x[y]]") is None
    assert extract_state_names("[x[y]]") is None
    with raises(ValueError):
        extract_state_names(None)

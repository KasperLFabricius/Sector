"""Native client protocol for callable Streamlit pages and genuine widget events."""

from streamlit.testing.v1 import AppTest

APP = r'''
import streamlit as st

def home():
    st.write("Home page")
    if st.button("Open detail", key="open_detail"):
        st.switch_page(detail_page)

def detail():
    st.write("Detail page")
    st.number_input("Value", key="detail_value", value=1)
    if st.button("Return home", key="return_home"):
        st.switch_page(home_page)

home_page = st.Page(home, title="Home", url_path="home", default=True)
detail_page = st.Page(detail, title="Detail", url_path="detail")
st.navigation([home_page, detail_page]).run()
'''


def test_callable_page_retains_actual_client_route_across_widget_event_and_instances():
    first = AppTest.from_string(APP).run()
    second = AppTest.from_string(APP).run()
    assert first.button(key="open_detail")
    assert second.button(key="open_detail")
    first.button(key="open_detail").click().run()
    assert first.number_input(key="detail_value").value == 1
    first.number_input(key="detail_value").set_value(7).run()
    assert not first.exception
    assert first.number_input(key="detail_value").value == 7
    assert first.button(key="return_home")
    second.run()
    assert second.button(key="open_detail")
    assert not second.number_input
    first.button(key="return_home").click().run()
    assert first.button(key="open_detail")
    assert not first.number_input
    first.run()
    assert first.button(key="open_detail")
    assert not first.exception

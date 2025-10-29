import nukescripts 

from coffeeboard.coffee_board import CoffeeBoard


def create_reference_board():
    nukescripts.panels.registerWidgetAsPanel(
        'CoffeeBoard',
        'Coffee Board',
        'com.coffeeveinstudio.CoffeeBoard',
    )

create_reference_board()
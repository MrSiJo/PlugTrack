from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, FloatField, IntegerField, BooleanField, SelectField, TextAreaField, DateField
from wtforms.validators import DataRequired, Email, Length, Optional, NumberRange, ValidationError
from datetime import date

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    password = PasswordField('Password', validators=[DataRequired()])

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired()])
    
    def validate_confirm_password(self, field):
        if self.password.data != field.data:
            raise ValidationError('Passwords must match')

class CarForm(FlaskForm):
    make = StringField('Make', validators=[DataRequired(), Length(max=100)])
    model = StringField('Model', validators=[DataRequired(), Length(max=100)])
    battery_kwh = FloatField('Battery Capacity (kWh)', validators=[DataRequired(), NumberRange(min=0.1)])
    efficiency_mpkwh = FloatField('Efficiency (mi/kWh)', validators=[Optional(), NumberRange(min=0.1)])
    active = BooleanField('Active')
    recommended_full_charge_enabled = BooleanField('Enable Recommended Full Charge')
    recommended_full_charge_frequency_value = IntegerField('Frequency Value', validators=[Optional(), NumberRange(min=1)])
    recommended_full_charge_frequency_unit = SelectField('Frequency Unit', 
                                                       choices=[('days', 'Days'), ('months', 'Months')],
                                                       validators=[Optional()])

class ChargingSessionForm(FlaskForm):
    car_id = SelectField('Car', coerce=int, validators=[DataRequired()])
    date = DateField('Date', validators=[DataRequired()], default=date.today)
    odometer = IntegerField('Odometer (miles)', validators=[DataRequired(), NumberRange(min=0)])
    charge_type = SelectField('Charge Type', choices=[('AC', 'AC'), ('DC', 'DC')], validators=[DataRequired()])
    charge_speed_kw = FloatField('Charge Speed (kW)', validators=[DataRequired(), NumberRange(min=0.1)])
    location_label = StringField('Location', validators=[DataRequired(), Length(max=200)])
    charge_network = StringField('Charge Network', validators=[Optional(), Length(max=100)])
    charge_delivered_kwh = FloatField('Charge Delivered (kWh)', validators=[DataRequired(), NumberRange(min=0.1)])
    duration_mins = IntegerField('Duration (minutes)', validators=[DataRequired(), NumberRange(min=1)])
    cost_per_kwh = FloatField('Cost per kWh', validators=[DataRequired(), NumberRange(min=0)])
    soc_from = IntegerField('SoC From (%)', validators=[DataRequired(), NumberRange(min=0, max=100)])
    soc_to = IntegerField('SoC To (%)', validators=[DataRequired(), NumberRange(min=0, max=100)])
    notes = TextAreaField('Notes', validators=[Optional()])
    
    def validate_soc_to(self, field):
        if self.soc_from.data and field.data and field.data <= self.soc_from.data:
            raise ValidationError('SoC To must be greater than SoC From')

class HomeChargingRateForm(FlaskForm):
    rate_per_kwh = FloatField('Rate per kWh', validators=[DataRequired(), NumberRange(min=0)])
    valid_from = DateField('Valid From', validators=[DataRequired()])
    valid_to = DateField('Valid To', validators=[Optional()])
    
    def validate_valid_to(self, field):
        if self.valid_from.data and field.data and field.data <= self.valid_from.data:
            raise ValidationError('Valid To must be after Valid From')

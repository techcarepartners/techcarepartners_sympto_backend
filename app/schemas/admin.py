from pydantic import BaseModel


class ApproveDoctorRequest(BaseModel):
    doctor_id: str
    approved: bool
    notify: bool = True


class SetMembershipRequest(BaseModel):
    doctor_id: str
    is_member: bool
    notify: bool = True


class AdminAppointmentActionRequest(BaseModel):
    appointment_id: str

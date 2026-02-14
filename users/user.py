from sqlmodel import SQLModel, Field
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class UserBase(SQLModel):
    username: str = Field(index=True)
    email: str
    fullname: str | None = None

class UserCreate(UserBase):
    password: str

class UserRead(UserBase):
    id: int
    
class User(UserBase, table=True):
    __tablename__ = "users"
    id: int | None = Field(default=None, primary_key=True)
    hashed_password: str

    def verify_password(self, password):
        return pwd_context.verify(password, self.hashed_password)
    
def get_user(db, username: str):
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        return None
    return UserRead(**user.dict())

def create_user(db, user: UserCreate):
    hashed_password = pwd_context.hash(user.password)
    db_user = User(username=user.username, email=user.email, fullname=user.fullname, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return UserRead(**db_user.dict())
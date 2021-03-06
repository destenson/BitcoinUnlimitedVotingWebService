from sqlalchemy import LargeBinary, Integer, Float, String, Column, ForeignKey, Boolean
from sqlalchemy.orm import relationship, reconstructor
import bitcoin
from butype import *
from tmemberlist import MemberList
import config


class Action(db.Model, BUType):
    """A signed action. A vote ballot is a special kind of signed
    action.
    """
    __tablename__="action"

    id = Column(Integer, primary_key=True)
    x_json = Column(LargeBinary, nullable=False)
    x_sha256 = Column(String(length=64), nullable=False, unique=True)    

    author_id = Column(Integer, ForeignKey("member.id"), nullable=False)
    author = relationship("Member", uselist=False)

    action_string = Column(String, nullable=False)

    member_list_id = Column(Integer, ForeignKey("member_list.id"), nullable=False)
    member_list = relationship("MemberList", uselist=False)

    # Time stamp of creation in DB
    # used for member voting eligibility calculations etc.
    timestamp = Column(Float, nullable=False)
                       
    signature = Column(String, nullable=False)

    def __init__(self,
                 author,
                 action_string,
                 signature):
        self.timestamp = time.time()

        self.author = author
        self.action_string = action_string
        self.signature = signature
        
        # FIXME: is base64.b64decode(...) safe?
        try:
            pub=bitcoin.ecdsa_recover(action_string, signature)
        except:
            raise jvalidate.ValidationError("Signature or action string invalid.")
        
        addr=author.address
        addr_from_pub=bitcoin.pubkey_to_address(pub)

        # is this enough? FIXME: review!
        # FIXME: check type(?) bug in bitcoin.ecsda_verify_addr
        if not addr == addr_from_pub:
            raise jvalidate.ValidationError(
                "Signature validation failed (%s, %s, %s)." % (repr(action_string), signature, addr))

        self.action_string = action_string

        self.reconstruct(fresh=True)
        self.xUpdate()

    @reconstructor
    def reconstruct(self, fresh=False):
        from actionparser import ActionParser
        L1=len(config.action_prefix)
        L2=64
        if (self.action_string[:L1] !=
            config.action_prefix):
            raise jvalidate.ValidationError(
                "Action is not prefixed with '%s'." %
                config.action_prefix)
        
        member_hash=self.action_string[L1:L1+L2]

        member_list = MemberList.by_hash(member_hash)
        if member_list is None:
            raise jvalidate.ValidationError("Action with member list '%s' not found."
                                            % member_hash)

        if fresh:
            if not member_list.current():
                raise jvalidate.ValidationError("Member list needs to be current for new action.")
        else:
            if member_list != self.member_list: # pragma: no cover
                raise jvalidate.ValidationError("Member list do not match in reconstructor (%s, %s)." % (member_list, self.member_list))
        
        self.member_list = member_list
        
        if self.author not in self.member_list.members:
            raise jvalidate.ValidationError("Action author not in member list.")

        self.actstr = self.action_string[L1+L2+1:]
        self.parser=ActionParser(self)

    def apply(self, upload, data):
        return self.parser.apply(upload, data)
        
    def toJ(self):
        return defaultExtend(self, {
            "author" : self.author.toJ(),
            "action_string" : self.action_string,
            "signature" : self.signature,
            "timestamp" : self.timestamp
        })

    def dependencies(self):
        return [self.author,
                self.member_list]
    

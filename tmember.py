import time
import re
import logging
from sqlalchemy import LargeBinary, Integer, Float, String, Column, ForeignKey, Boolean
from sqlalchemy.orm import relationship
import sqlalchemy.orm.exc
from sqlalchemy.orm import load_only
from sqlalchemy import func
from jvalidate import ValidationError
from butype import *
from tglobal import Global
from atypes import tMemberName, tAddress
import config
from tmember_assoc import members_in_memberlists

log=logging.getLogger(__name__)

sanitize_membername=tMemberName
sanitize_bitcoinaddr=tAddress

class Member(db.Model, BUType):
    """A BU member with name and Bitcoin address and memberlists s/he belongs to. 
    """
    __tablename__="member"

    id = Column(Integer, primary_key=True)
    x_json = Column(LargeBinary, nullable=False)
    x_sha256 = Column(String(length=64), nullable=False, unique=True)

    # no two members with same nick 
    name = Column(String, nullable=False, unique=True)

    # same for addresses - are burned when used up
    address = Column(String, nullable=False, unique=True)

    # lists this member is part of
    member_lists = relationship("MemberList", secondary = members_in_memberlists,
                                back_populates="members")

    @classmethod
    def by_name(cls, name):
        """ Return member object by giving member name. """
        try:
            return cls.query.filter(cls.name  == name).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    @classmethod
    def by_address(cls, address):
        """ Return member object by giving member address. """
        try:
            return cls.query.filter(cls.address  == address).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None
        
    def __init__(self,
                 name,
                 address):
        sanitize_membername(name)
        sanitize_bitcoinaddr(address)
        
        self.name = name
        self.address = address

        self.xUpdate()
        
    def toJ(self):
        return defaultExtend(self, {
            "name" : self.name,
            "address" : self.address
        })

    def dependencies(self):
        return []

    def last_vote_action(self):
        """ Returns the time (unix epoch) this member voted last. 0.0 if member never voted yet. """
        from taction import Action
        from tproposalvoteresult import ProposalVoteResult
        from tmemberelectionresult import MemberElectionResult
        
        # last proposal vote
        last_pvote = (db.session
                      .query(func.max(Action.timestamp))
                      .filter(Action.author == self)
                      .filter(ProposalVoteResult.ballots.any(id=Action.id))
                      .one())[0]
        if last_pvote is None:
            last_pvote = 0.0

        # last member vote
        last_mvote = (db.session
                      .query(func.max(Action.timestamp))
                      .filter(Action.author == self)
                      .filter(MemberElectionResult.ballots.any(id=Action.id))
                      .one())[0]
        if last_mvote is None:
            last_mvote = 0.0

        return max(last_pvote, last_mvote)
    
    def last_member_confirmation(self):
        """Returns the time (unix epoch) this member was last voted on. 
        The time a member is voted in is assumed to be the time of
        the last ballot cast on that particular vote. Returns 0.0 if the
        member was never confirmed (member existed before voting system).

        Note that a recent vote does not mean eligibility, as this
        does not check whether the vote was accepted by
        majority. Check the member list for that.
        """
        from taction import Action
        from tmemberelectionresult import MemberElectionResult
        
        last_conf = (db.session
                     .query(func.max(Action.timestamp))
                     .filter(MemberElectionResult.new_member == self)
                     .filter(MemberElectionResult.ballots.any(id=Action.id))
                     .one())[0]

        return 0.0 if last_conf is None else last_conf
    
    def eligible(self):
        """Returns true iff member is eligible to vote. 
        
        Remark:

        Note that the above two methods, last_member_confirmation()
        and last_vote_action() can NOT be used alone to determine member
        eligibility in all cases, as members who are on the initial member list
        will have an unknown time of last-vote from just the above
        queries.  

        That's why a global configuration setting for those members
        will be used instead. In case a member has no configured external
        time of last vote and is not otherwise eligible, it is deemed
        not eligible to vote.

        """
        log.debug("Checking eligibility for: %s", self.name)
        if not self.current():
            log.debug("Not eligible, not a current member.")
            return False
        
        t=time.time()
        t_expire = t - config.member_expiry_time

        log.debug("Expiry time, relative to now:%f", t_expire - t)

        lva = self.last_vote_action()
        lmc = self.last_member_confirmation()

        log.debug("Last vote action relative to now:%f", lva - t)
        log.debug("Last member confirmation vote relative to now:%f", lmc - t)
        t_elig = max(lva, lmc)
        
        if t_elig > 0.0:
            # regular case: member has voted or been voted in
            eligible = t_elig > t_expire
            log.debug("Regular case eligibility check: %d", eligible)
            return eligible
        else:
            t_last = Global.member_last_vote_time(self)
            if t_last is None:
                log.debug("No last vote time for member set.")
            else:
                log.debug("Check from preset last vote date, relative to now: %f", t_last - t)
            if t_last is None:
                log.debug("Unknown preset last vote date -> not eligible")
                # member has unknown time of last vote -> not eligible
                return False
            else:
                eligible = Global.member_last_vote_time(self) > t_expire
                log.debug("Eligibility from config: %d", eligible)
                # member eligibility is determined from Global config
                return eligible

    def current(self):
        """ Is this member in current member list? """
        if Global.current_member_list() is not None:
            return self in Global.current_member_list().members
        else:
            return False
        
        
